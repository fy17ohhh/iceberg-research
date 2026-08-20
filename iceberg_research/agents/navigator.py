from __future__ import annotations

import hashlib
import json
import logging
import re

import json_repair
from openai.types.chat import ChatCompletionMessage

from ..base import AgentBase, Message, llm_client
from ..context import ContextBuilder
from ..api.schemas import NavigationResult
from .planning_models import SubQuestion
from .prompts import (
    NAVIGATOR_PLAN_USER,
    NAVIGATOR_REPLAN_USER,
    NAVIGATOR_SYSTEM,
    NAVIGATOR_INTAKE_SYSTEM,
    NAVIGATOR_INTAKE_USER,
    NAVIGATOR_REFINE_USER,
)
from .sonar_models import ReviewItem, ReviewResult


logger = logging.getLogger(__name__)
display = logging.getLogger("iceberg_research.display")

_SHORT_AMBIGUOUS_QUERY = re.compile(r"^[A-Za-z][A-Za-z0-9._+-]{0,8}$")

INTAKE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "analyze_research_request",
        "description": "Determine whether a research request is sufficiently scoped.",
        "parameters": {
            "type": "object",
            "properties": {
                "is_clear": {"type": "boolean"},
                "research_brief": {"type": "string"},
                "suggested_directions": {
                    "type": "array", "items": {"type": "string"}
                },
                "message": {"type": "string"},
            },
            "required": ["is_clear"],
        },
    },
}

LOCAL_INTAKE_JSON_INSTRUCTION = """
Native function calling is unavailable. Return exactly one JSON object with these
keys: is_clear (boolean), research_brief (string), message (string), and
suggested_directions (string array). Do not use Markdown or a tool name.
"""


class Navigator(AgentBase):
    """Owns research intake, planning, and targeted replanning."""

    def __init__(
        self,
        llm: llm_client,
        context_builder: ContextBuilder,
        max_steps: int,
        name: str = "navigator",
        system_prompt: str = NAVIGATOR_SYSTEM,
        plan_user_prompt: str = NAVIGATOR_PLAN_USER,
        creative_temperature: float = 0.2,
    ) -> None:
        super().__init__(name, llm, context_builder, system_prompt)
        self.max_steps = max_steps
        self.plan_user_prompt = plan_user_prompt
        self.intake_system_prompt = NAVIGATOR_INTAKE_SYSTEM
        self.creative_temperature = creative_temperature
        self.output_schema = {
            "type": "function",
            "function": {
                "name": "create_research_plan",
                "description": (
                    "Analyze research dimensions, then submit a minimal, "
                    "non-overlapping set of research sub-questions."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "analysis": {
                            "type": "string",
                            "description": (
                                "Dimension analysis and explanation of how the "
                                "questions cover the brief without overlap."
                            ),
                        },
                        "sub_questions": {
                            "type": "array",
                            "items": SubQuestion.model_json_schema(),
                        },
                    },
                    "required": ["analysis", "sub_questions"],
                },
            },
        }

    def run(self, prompt: str, **kwargs) -> str:
        result = self.analyze(prompt)
        if result.is_clear:
            return result.brief or prompt
        if result.message:
            display.info("\n%s", result.message)
        for index, direction in enumerate(result.directions, 1):
            display.info("  %d. %s", index, direction)
        response = input("> ").strip()
        if result.directions and response.isdigit():
            selected = int(response) - 1
            if 0 <= selected < len(result.directions):
                response = result.directions[selected]
        return self.refine(raw_query=prompt, user_response=response)

    def analyze(self, raw_query: str) -> NavigationResult:
        query = raw_query.strip()
        if self._is_ambiguous_short_query(query):
            logger.info("[Navigator] short or acronym-like query bypassed LLM intake")
            return self._ambiguous_query_result(query)

        messages = [
            {"role": "system", "content": self.intake_system_prompt},
            {"role": "user", "content": NAVIGATOR_INTAKE_USER.format(raw_query=query)},
        ]
        local_json_mode = bool(getattr(self.llm, "disable_tools", False))
        if local_json_mode:
            messages[0] = {
                **messages[0],
                "content": f"{self.intake_system_prompt}\n\n{LOCAL_INTAKE_JSON_INSTRUCTION}",
            }
            response = self.llm.invoke(
                messages=messages, temperature=0.2, tag="navigator:intake:json"
            )
            arguments = self._parse_json_arguments(response.content or "")
        else:
            response = self.llm.invoke(
                messages=messages,
                tools=[INTAKE_SCHEMA],
                tool_choice={
                    "type": "function",
                    "function": {"name": "analyze_research_request"},
                },
                temperature=0,
                tag="navigator:intake",
            )
            raw_arguments = (
                response.tool_calls[0].function.arguments
                if response.tool_calls
                else response.content or ""
            )
            arguments = self._parse_json_arguments(raw_arguments)

        if arguments is None:
            logger.warning("[Navigator] intake response is invalid; requesting query context")
            return self._ambiguous_query_result(query)
        return self._intake_result_from_arguments(arguments, query)

    def refine(self, raw_query: str, user_response: str) -> str:
        if not user_response.strip():
            return raw_query
        messages = [
            {"role": "system", "content": self.intake_system_prompt},
            {
                "role": "user",
                "content": NAVIGATOR_REFINE_USER.format(
                    raw_query=raw_query, user_response=user_response
                ),
            },
        ]
        response = self.llm.invoke(
            messages=messages,
            temperature=self.creative_temperature,
            tag="navigator:refine",
        )
        return (response.content or "").strip() or user_response.strip() or raw_query

    @staticmethod
    def _is_ambiguous_short_query(query: str) -> bool:
        return bool(_SHORT_AMBIGUOUS_QUERY.fullmatch(query))

    @staticmethod
    def _ambiguous_query_result(query: str) -> NavigationResult:
        subject = query or "这个输入"
        return NavigationResult(
            is_clear=False,
            message=(
                f"“{subject}” 的含义还不明确。请告诉我：\n"
                "1. 它的全称或所属领域；\n"
                "2. 你想了解概念、实现、对比还是应用；\n"
                "3. 希望研究的时间范围或业务场景。"
            ),
            directions=[],
        )

    @staticmethod
    def _parse_json_arguments(raw: str) -> dict | None:
        if not raw or not raw.strip():
            return None
        candidates = [raw.strip()]
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            candidates.append(match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    parsed = json_repair.loads(candidate)
                except Exception:
                    continue
            if isinstance(parsed, dict) and isinstance(parsed.get("is_clear"), bool):
                return parsed
        return None

    def _intake_result_from_arguments(
        self, arguments: dict, raw_query: str
    ) -> NavigationResult:
        if arguments["is_clear"]:
            return NavigationResult(
                is_clear=True,
                brief=(arguments.get("research_brief") or raw_query).strip(),
            )
        message = str(arguments.get("message") or "").strip()
        directions = [
            str(item).strip()
            for item in arguments.get("suggested_directions", [])
            if str(item).strip()
        ]
        if not message and not directions:
            return self._ambiguous_query_result(raw_query)
        return NavigationResult(
            is_clear=False,
            message=message or self._ambiguous_query_result(raw_query).message,
            directions=directions,
        )

    def plan(self, research_brief: str) -> list[SubQuestion]:
        prompt = self.plan_user_prompt.format(
            research_brief=research_brief,
            max_steps=self.max_steps,
        )
        return self._invoke_plan(prompt=prompt, tag="navigator:plan")

    def replan(
        self,
        research_brief: str,
        approved_items: list[ReviewItem],
        sonar_result: ReviewResult,
    ) -> list[SubQuestion]:
        approved_questions = "\n".join(
            f"- [{item.sub_question_id}] {item.sub_question}"
            for item in approved_items
        ) or "(none)"
        replan_items = "\n".join(
            (
                f"- pair_id={review.pair_id}: "
                f"{review.failed_criteria() or review.retry_feedback}"
            )
            for review in sonar_result.note_reviews
            if review.verdict == "replan"
        ) or "(none)"
        coverage_gaps = "\n".join(
            f"- {gap.dimension}: {gap.reason}; suggested scope: {gap.suggested_scope}"
            for gap in sonar_result.coverage_gaps
        ) or "(none)"
        redundancies = "\n".join(
            (
                f"- pair_ids={issue.pair_ids}; overlap="
                f"{issue.overlapping_sources}; {issue.recommendation}"
            )
            for issue in sonar_result.redundancy_issues
        ) or "(none)"
        prompt = NAVIGATOR_REPLAN_USER.format(
            research_brief=research_brief,
            approved_questions=approved_questions,
            replan_items=replan_items,
            coverage_gaps=coverage_gaps,
            redundancy_issues=redundancies,
            max_steps=self.max_steps,
        )
        return self._invoke_plan(prompt=prompt, tag="navigator:replan")

    def _invoke_plan(self, prompt: str, tag: str) -> list[SubQuestion]:
        self._history.append(Message(content=prompt, role="user"))
        messages = self._build_messages()
        kwargs = {
            "messages": messages,
            "tool_choice": "required",
            "tools": [self.output_schema],
            "temperature": 0,
            "tag": tag,
        }
        try:
            response = self.llm.invoke(**kwargs)
            result = self._parse_tool_response(response)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[Navigator] plan JSON 解析/校验失败，重试一次")
            response = self.llm.invoke(**kwargs)
            result = self._parse_tool_response(response)
        self._record_response(response, result)
        questions = [
            SubQuestion(**item) for item in result.get("sub_questions", [])
        ]
        questions = self._normalize_ids(questions)
        logger.info("[%s] 生成 %d 个子问题", tag, len(questions))
        return questions

    @staticmethod
    def _normalize_ids(questions: list[SubQuestion]) -> list[SubQuestion]:
        used: set[str] = set()
        for question in questions:
            candidate = re.sub(
                r"[^a-z0-9]+",
                "_",
                (question.id or question.label).lower(),
            ).strip("_")[:36]
            if not candidate or candidate in used:
                digest = hashlib.sha1(
                    question.question.encode("utf-8")
                ).hexdigest()[:10]
                candidate = f"sq_{digest}"
            elif not candidate.startswith("sq_"):
                candidate = f"sq_{candidate}"
            while candidate in used:
                candidate = f"{candidate}_{len(used) + 1}"
            question.id = candidate
            used.add(candidate)
        return questions

    @staticmethod
    def _parse_tool_response(response: ChatCompletionMessage) -> dict:
        if response.tool_calls:
            raw = response.tool_calls[0].function.arguments
        else:
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if raw.startswith("create_research_plan"):
                raw = raw[len("create_research_plan") :].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = json_repair.loads(raw)
        if isinstance(parsed, list):
            return {"analysis": "", "sub_questions": parsed}
        return parsed

    def _record_response(
        self, response: ChatCompletionMessage, result: dict
    ) -> None:
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            fixed = tool_call.model_dump()
            fixed["function"]["arguments"] = json.dumps(result, ensure_ascii=False)
            self._history.append(
                Message(
                    content=response.content,
                    role="assistant",
                    tool_calls=[fixed],
                )
            )
            self._history.append(
                Message(
                    content=json.dumps(result, ensure_ascii=False),
                    role="tool",
                    tool_call_id=tool_call.id,
                )
            )
        else:
            self._history.append(
                Message(content=response.content or "", role="assistant")
            )


__all__ = ["Navigator", "SubQuestion"]
