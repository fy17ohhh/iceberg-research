import json

from iceberg_research.base.llm_client import (
    LLMClient,
    _model_id_from_env,
    _resolve_model_env,
)


def test_lowercase_model_id_alias_is_supported(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_ID", raising=False)
    monkeypatch.setenv("model_id", "llama3.2:latest")

    assert _model_id_from_env() == "llama3.2:latest"


def test_llama_model_uses_local_ollama_defaults(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_DISABLE_TOOLS", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    api_key, base_url, extra_body, disable_tools = _resolve_model_env(
        "llama3.2:latest"
    )

    assert api_key == "ollama"
    assert base_url == "http://localhost:11434/v1"
    assert extra_body is None
    assert disable_tools is True


def test_ollama_env_takes_precedence_over_cloud_model_prefix(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("OLLAMA_DISABLE_TOOLS", raising=False)

    api_key, base_url, extra_body, disable_tools = _resolve_model_env(
        "deepseek-r1:7b"
    )

    assert api_key == "ollama"
    assert base_url == "http://localhost:11434/v1"
    assert extra_body is None
    assert disable_tools is True


def test_local_text_json_can_be_synthesized_as_tool_call():
    schema = {
        "type": "function",
        "function": {
            "name": "create_research_plan",
            "parameters": {
                "type": "object",
                "properties": {"sub_questions": {"type": "array"}},
            },
        },
    }
    content = json.dumps(
        {
            "analysis": "local planning",
            "sub_questions": [{"id": "sq_1", "question": "What changed?"}],
        }
    )

    calls = LLMClient._parse_text_tool_calls(
        content=content,
        tools=[schema],
        tool_choice="required",
    )

    assert len(calls) == 1
    assert calls[0].function.name == "create_research_plan"
    assert json.loads(calls[0].function.arguments)["analysis"] == "local planning"


def test_local_text_function_syntax_can_be_synthesized_as_tool_call():
    schema = {
        "type": "function",
        "function": {
            "name": "search_web",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}},
            },
        },
    }

    calls = LLMClient._parse_text_tool_calls(
        content='search_web({"query": "ollama tool calling"})',
        tools=[schema],
        tool_choice="auto",
    )

    assert len(calls) == 1
    assert calls[0].function.name == "search_web"
    assert json.loads(calls[0].function.arguments) == {
        "query": "ollama tool calling"
    }
