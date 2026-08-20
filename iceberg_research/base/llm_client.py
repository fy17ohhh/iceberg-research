from __future__ import annotations

import json
import os, logging, re, time
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall, Function,
)
from dotenv import load_dotenv


load_dotenv()
logger = logging.getLogger(__name__)


def _model_id_from_env() -> str | None:
    return os.getenv("LLM_MODEL_ID") or os.getenv("MODEL_ID") or os.getenv("model_id")


def _provider_from_env() -> str | None:
    provider = os.getenv("LLM_PROVIDER") or os.getenv("MODEL_PROVIDER")
    return provider.strip().lower() if provider else None


def _ollama_env_configured() -> bool:
    return bool(os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_API_KEY"))


MODEL_PROFILES = {
    "deepseek": {
        "api_key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "extra_body": {"thinking": {"type": "disabled"}},
    },
    "glm": {
        "api_key": "GLM_API_KEY",
        "base_url": "GLM_BASE_URL",
    },
    "gemini": {
        "api_key": "GOOGLE_API_KEY",
        "base_url": "GOOGLE_BASE_URL",
    },
    "gpt": {
        "api_key": "OPENAI_API_KEY",
        "base_url": "OPENAI_BASE_URL",
    },
    "qwen": {
        "api_key": "QWEN_API_KEY",
        "base_url": "QWEN_BASE_URL",
        "extra_body": {"enable_thinking": False},
    },
    "ollama": {
        "api_key": "OLLAMA_API_KEY",
        "base_url": "OLLAMA_BASE_URL",
        "default_api_key": "ollama",
        "default_base_url": "http://localhost:11434/v1",
        "disable_tools_env": "OLLAMA_DISABLE_TOOLS",
        "default_disable_tools": True,
    },
}


def _env_bool(name: str, default: bool = False) -> bool:
    if not name:
        return default
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_profile(prefix: str, profile: dict, model: str) -> tuple[str, str | None, dict | None, bool]:
    api_key_env = profile["api_key"]
    api_key = os.getenv(api_key_env) or profile.get("default_api_key")
    if not api_key:
        raise ValueError(
            f"模型 '{model}' 匹配到 '{prefix}'，"
            f"但环境变量 {api_key_env} 未设置"
        )

    base_url = None
    if "base_url" in profile:
        base_url_env = profile["base_url"]
        base_url = os.getenv(base_url_env) or profile.get("default_base_url")
        if not base_url:
            raise ValueError(
                f"模型 '{model}' 匹配到 '{prefix}'，"
                f"但环境变量 {base_url_env} 未设置"
            )

    return (
        api_key,
        base_url,
        profile.get("extra_body"),
        _env_bool(
            profile.get("disable_tools_env", ""),
            profile.get("default_disable_tools", False),
        ),
    )


def _resolve_model_env(model: str) -> tuple[str, str | None, dict | None, bool]:
    explicit_provider = _provider_from_env()
    if explicit_provider:
        if explicit_provider not in MODEL_PROFILES:
            raise ValueError(
                f"未知 LLM_PROVIDER '{explicit_provider}'，"
                f"支持的 provider: {list(MODEL_PROFILES.keys()) + ['claude']}"
            )
        return _resolve_profile(
            explicit_provider,
            MODEL_PROFILES[explicit_provider],
            model,
        )

    if _ollama_env_configured():
        return _resolve_profile("ollama", MODEL_PROFILES["ollama"], model)

    for prefix, profile in MODEL_PROFILES.items():
        if model.lower().startswith(prefix):
            return _resolve_profile(prefix, profile, model)

    all_prefixes = list(MODEL_PROFILES.keys()) + ["claude"]
    raise ValueError(
        f"未知模型 '{model}'，支持的前缀: {all_prefixes}。"
        "如使用 Ollama，请设置 LLM_PROVIDER=ollama 或 OLLAMA_BASE_URL。"
    )


class LLMClient:
    def __init__(
        self,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
        timeout: int = None,
    ):
        self.model = model or _model_id_from_env()
        if not self.model:
            raise ValueError(
                "未指定模型。请使用 --model 参数或在 .env 中设置 LLM_MODEL_ID"
            )

        self.timeout = timeout or int(os.getenv("LLM_TIMEOUT", 60))
        self._is_claude = self.model.lower().startswith("claude")
        self.disable_tools = False

        if self._is_claude:
            try:
                import anthropic
            except ImportError:
                raise ImportError(
                    "Claude 模型需要安装 anthropic SDK: uv add anthropic"
                )
            _api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not _api_key:
                raise ValueError("Claude 模型需要设置环境变量 ANTHROPIC_API_KEY")
            self._anthropic_client = anthropic.Anthropic(
                api_key=_api_key, timeout=self.timeout
            )
            self.extra_body = None
            self.client = None
        else:
            if api_key and base_url:
                self.extra_body = None
                self.disable_tools = _env_bool("LLM_DISABLE_TOOLS", False)
            else:
                (
                    api_key,
                    base_url,
                    self.extra_body,
                    self.disable_tools,
                ) = _resolve_model_env(self.model)
            self.client = OpenAI(
                api_key=api_key, base_url=base_url, timeout=self.timeout
            )

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

    def reset_stats(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_calls = 0

    def invoke(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0,
        tools=None,
        tool_choice=None,
        max_tokens: int = 4096,
        tag: str = "",
    ) -> ChatCompletionMessage:
        if self._is_claude:
            return self._invoke_claude(
                messages, temperature, tools, tool_choice, max_tokens, tag
            )

        if tool_choice is None:
            tool_choice = "auto" if tools else None
        request_messages = messages
        request_tools = tools if tools else None
        request_tool_choice = tool_choice
        synthesize_tools = bool(tools and self.disable_tools)
        if synthesize_tools:
            request_messages = self._with_text_tool_instruction(
                messages, tools, tool_choice
            )
            request_tools = None
            request_tool_choice = None

        start = time.time()
        response = self.client.chat.completions.create(
            messages=request_messages,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            tool_choice=request_tool_choice,
            tools=request_tools,
            extra_body=self.extra_body,
        )
        elapsed = time.time() - start

        msg = response.choices[0].message
        if synthesize_tools:
            tool_calls = self._parse_text_tool_calls(
                msg.content or "", tools, tool_choice
            )
            if tool_calls:
                msg = ChatCompletionMessage(
                    role="assistant",
                    content=msg.content,
                    tool_calls=tool_calls,
                )
        usage = response.usage
        self._track_usage(
            getattr(usage, "prompt_tokens", 0) if usage else 0,
            getattr(usage, "completion_tokens", 0) if usage else 0,
            elapsed, tag, msg,
        )
        return msg

    # ---- Claude adapter ----

    def _invoke_claude(self, messages, temperature, tools, tool_choice, max_tokens, tag):
        system, anthropic_msgs = self._translate_messages(messages)

        anthropic_tools = None
        if tools:
            anthropic_tools = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]

        anthropic_tc = None
        if anthropic_tools:
            if tool_choice is None or tool_choice == "auto":
                anthropic_tc = {"type": "auto"}
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                anthropic_tc = {"type": "tool", "name": tool_choice["function"]["name"]}
            elif tool_choice == "none":
                anthropic_tools = None

        kwargs = {
            "model": self.model,
            "messages": anthropic_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools
        if anthropic_tc:
            kwargs["tool_choice"] = anthropic_tc

        start = time.time()
        response = self._anthropic_client.messages.create(**kwargs)
        elapsed = time.time() - start

        content = None
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=block.id,
                        type="function",
                        function=Function(
                            name=block.name,
                            arguments=json.dumps(block.input, ensure_ascii=False),
                        ),
                    )
                )

        msg = ChatCompletionMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )
        self._track_usage(
            response.usage.input_tokens,
            response.usage.output_tokens,
            elapsed, tag, msg,
        )
        return msg

    @staticmethod
    def _translate_messages(messages):
        """OpenAI message list -> Anthropic (system, messages)."""
        system_parts = []
        result = []

        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg["role"]

            if role == "system":
                system_parts.append(msg["content"])
                i += 1

            elif role == "user":
                result.append({"role": "user", "content": msg["content"]})
                i += 1

            elif role == "assistant":
                blocks = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": msg["content"]})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        args = tc["function"]["arguments"]
                        blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(args) if isinstance(args, str) else args,
                        })
                if not blocks:
                    blocks.append({"type": "text", "text": ""})
                result.append({"role": "assistant", "content": blocks})
                i += 1

            elif role == "tool":
                tool_results = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": messages[i]["tool_call_id"],
                        "content": messages[i]["content"] or "",
                    })
                    i += 1
                result.append({"role": "user", "content": tool_results})

            else:
                i += 1

        system = "\n\n".join(system_parts) if system_parts else None
        return system, result

    # ---- shared ----

    @staticmethod
    def _with_text_tool_instruction(messages, tools, tool_choice):
        tool_specs = []
        for tool in tools:
            function = tool.get("function", {})
            tool_specs.append(
                {
                    "name": function.get("name"),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
        forced_tool = None
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            forced_tool = tool_choice.get("function", {}).get("name")
        elif tool_choice == "required" and len(tool_specs) == 1:
            forced_tool = tool_specs[0]["name"]

        if forced_tool:
            instruction = (
                "The current local model endpoint does not use native function "
                f"calling. Respond with only the JSON arguments for the function "
                f"`{forced_tool}`. Do not wrap the JSON in Markdown. Schema:\n"
                f"{json.dumps(tool_specs, ensure_ascii=False)}"
            )
        else:
            instruction = (
                "The current local model endpoint does not use native function "
                "calling. When you need a tool, respond with one or more lines in "
                "this exact format: tool_name({\"arg\": \"value\"}). When you are "
                "done, answer normally. Available tools:\n"
                f"{json.dumps(tool_specs, ensure_ascii=False)}"
            )

        if messages and messages[0].get("role") == "system":
            updated = [dict(messages[0])]
            updated[0]["content"] = f"{updated[0].get('content', '')}\n\n{instruction}"
            updated.extend(messages[1:])
            return updated
        return [{"role": "system", "content": instruction}, *messages]

    @staticmethod
    def _parse_text_tool_calls(content: str, tools, tool_choice) -> list[ChatCompletionMessageToolCall]:
        if not content:
            return []
        tool_names = {
            tool.get("function", {}).get("name"): tool
            for tool in tools
            if tool.get("function", {}).get("name")
        }
        forced_tool = None
        if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
            forced_tool = tool_choice.get("function", {}).get("name")
        elif tool_choice == "required" and len(tool_names) == 1:
            forced_tool = next(iter(tool_names))

        if forced_tool and forced_tool in tool_names:
            arguments = LLMClient._extract_json_arguments(content)
            if arguments is not None:
                return [
                    ChatCompletionMessageToolCall(
                        id="local_tool_0",
                        type="function",
                        function=Function(
                            name=forced_tool,
                            arguments=json.dumps(arguments, ensure_ascii=False),
                        ),
                    )
                ]

        calls = []
        pattern = rf"\b({'|'.join(re.escape(name) for name in tool_names)})\((.+?)\)"
        for index, match in enumerate(re.finditer(pattern, content, flags=re.DOTALL)):
            name = match.group(1)
            raw_args = match.group(2).strip()
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                arguments = None
            if arguments is None and len(tool_names) == 1:
                arguments = LLMClient._single_string_argument(
                    tool_names[name], raw_args
                )
            if isinstance(arguments, dict):
                calls.append(
                    ChatCompletionMessageToolCall(
                        id=f"local_tool_{index}",
                        type="function",
                        function=Function(
                            name=name,
                            arguments=json.dumps(arguments, ensure_ascii=False),
                        ),
                    )
                )
        return calls

    @staticmethod
    def _extract_json_arguments(content: str):
        raw = content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if "(" in raw and raw.endswith(")"):
            raw = raw[raw.find("(") + 1 : -1].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _single_string_argument(tool, raw_args: str) -> dict | None:
        stripped = raw_args.strip()
        if (
            len(stripped) >= 2
            and stripped[0] in {"'", '"'}
            and stripped[-1] == stripped[0]
        ):
            stripped = stripped[1:-1]
        params = tool.get("function", {}).get("parameters", {})
        required = params.get("required") or []
        properties = params.get("properties") or {}
        if required:
            return {required[0]: stripped}
        if properties:
            return {next(iter(properties)): stripped}
        return None

    def _track_usage(self, prompt_tokens, completion_tokens, elapsed, tag, msg):
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_calls += 1
        total = prompt_tokens + completion_tokens
        label = f"[LLM:{tag}]" if tag else "[LLM]"
        logger.info(
            "%s 响应: %.1fs, tokens=%d(in:%d+out:%d)",
            label, elapsed, total, prompt_tokens, completion_tokens,
        )
        logger.debug("%s 输出: %.500s", label, msg.content)


if __name__ == "__main__":
    try:
        agent = LLMClient()

        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that writes Python code.",
            },
            {"role": "user", "content": "请告诉我openai的SDK的常用代码和语法"},
        ]

        print("--- 调用LLM ---")
        response = agent.invoke(messages)
        if response:
            print("\n\n--- 完整模型响应 ---")
            print(response)

    except ValueError as e:
        print(e)
