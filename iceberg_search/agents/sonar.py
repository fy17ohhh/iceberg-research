from __future__ import annotations

import json
import logging
from copy import deepcopy

import json_repair
from openai.types.chat import ChatCompletionMessage

from ..base import AgentBase, Message, llm_client
from ..context import ContextBuilder
from .prompts import SONAR_REVIEW_USER, SONAR_SYSTEM
from .sonar_models import (
    CoverageGap,
    CriterionReview,
    NoteReview,
    RedundancyIssue,
    ReviewItem,
    ReviewResult,
)


logger = logging.getLogger(__name__)


class Sonar(AgentBase):
    """Independent quality gate for Diver notes."""

    def __init__(
        self,
        llm: llm_client,
        context_builder: ContextBuilder,
        name: str = "sonar",
        system_prompt: str = SONAR_SYSTEM,
        batch_size: int = 2,
        max_attempts: int = 3,
    ) -> None:
        super().__init__(name, llm, context_builder, system_prompt)
        self.batch_size = max(1, batch_size)
        self.max_attempts = max(1, max_attempts)
        self.review_schema = {
            "type": "function",
            "function": {
                "name": "submit_review",
                "description": (
                    "Submit one quality review for every requested pair_id, plus "
                    "portfolio-level coverage and redundancy findings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_reviews": {
                            "type": "array",
                            "items": NoteReview.model_json_schema(),
                        },
                        "coverage_gaps": {
                            "type": "array",
                            "items": CoverageGap.model_json_schema(),
                        },
                        "redundancy_issues": {
                            "type": "array",
                            "items": RedundancyIssue.model_json_schema(),
                        },
                    },
                    "required": [
                        "note_reviews",
                        "coverage_gaps",
                        "redundancy_issues",
                    ],
                },
            },
        }

    def run(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError("Sonar uses review(), not run()")

    def review(
        self,
        research_brief: str,
        pending_items: list[ReviewItem],
        approved_items: list[ReviewItem] | None = None,
    ) -> ReviewResult:
        all_reviews: list[NoteReview] = []
        gaps: dict[tuple[str, str], CoverageGap] = {}
        redundancies: dict[tuple[str, ...], RedundancyIssue] = {}
        portfolio_questions = [
            item.sub_question for item in [*(approved_items or []), *pending_items]
        ]

        for start in range(0, len(pending_items), self.batch_size):
            batch = pending_items[start : start + self.batch_size]
            unresolved = {item.pair_id: item for item in batch}

            for attempt in range(1, self.max_attempts + 1):
                if not unresolved:
                    break
                requested = list(unresolved.values())
                try:
                    partial = self._review_once(
                        research_brief=research_brief,
                        items=requested,
                        approved_items=approved_items or [],
                        portfolio_questions=portfolio_questions,
                        attempt=attempt,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Sonar] batch 第 %d/%d 次调用失败，保留全部 %d 条: %s",
                        attempt,
                        self.max_attempts,
                        len(unresolved),
                        exc,
                    )
                    continue
                seen_this_attempt: set[str] = set()
                for review in partial.note_reviews:
                    if (
                        review.pair_id not in unresolved
                        or review.pair_id in seen_this_attempt
                    ):
                        logger.warning(
                            "[Sonar] 忽略未知或重复 pair_id: %s",
                            review.pair_id,
                        )
                        continue
                    seen_this_attempt.add(review.pair_id)
                    all_reviews.append(review)
                    unresolved.pop(review.pair_id)

                for gap in partial.coverage_gaps:
                    gaps[(gap.dimension, gap.reason)] = gap
                for issue in partial.redundancy_issues:
                    redundancies[tuple(sorted(issue.pair_ids))] = issue

                if unresolved:
                    logger.warning(
                        "[Sonar] batch 返回不足，第 %d/%d 次后仍缺 %d 条",
                        attempt,
                        self.max_attempts,
                        len(unresolved),
                    )

            for item in unresolved.values():
                logger.error(
                    "[Sonar] pair_id=%s 多次未获评审，保守标记 retry",
                    item.pair_id,
                )
                all_reviews.append(self._missing_review_fallback(item.pair_id))

        order = {item.pair_id: index for index, item in enumerate(pending_items)}
        all_reviews.sort(key=lambda review: order.get(review.pair_id, len(order)))
        return ReviewResult(
            note_reviews=all_reviews,
            coverage_gaps=list(gaps.values()),
            redundancy_issues=list(redundancies.values()),
        )

    def _review_once(
        self,
        research_brief: str,
        items: list[ReviewItem],
        approved_items: list[ReviewItem],
        portfolio_questions: list[str],
        attempt: int,
    ) -> ReviewResult:
        approved = "\n".join(
            f"- [{item.sub_question_id}] {item.sub_question}"
            for item in approved_items
        ) or "(none)"
        portfolio = "\n".join(f"- {question}" for question in portfolio_questions)
        pairs = "\n".join(
            (
                f'<review_item pair_id="{item.pair_id}">\n'
                f"<sub_question>{item.sub_question}</sub_question>\n"
                f"<research_note>{item.research_note}</research_note>\n"
                "</review_item>"
            )
            for item in items
        )
        prompt = SONAR_REVIEW_USER.format(
            research_brief=research_brief,
            approved_questions=approved,
            portfolio_questions=portfolio,
            review_items=pairs,
            pair_count=len(items),
        )
        self._history.append(Message(content=prompt, role="user"))
        messages = self._build_messages()

        schema = deepcopy(self.review_schema)
        reviews_schema = schema["function"]["parameters"]["properties"]["note_reviews"]
        reviews_schema["minItems"] = len(items)
        reviews_schema["maxItems"] = len(items)
        kwargs = {
            "messages": messages,
            "tool_choice": "required",
            "tools": [schema],
            "temperature": 0,
            "tag": f"sonar:review:{attempt}",
        }
        response = self.llm.invoke(**kwargs)
        result = self._parse_tool_response(response)
        self._record_response(response, result)
        return ReviewResult(**result)

    @staticmethod
    def _parse_tool_response(response: ChatCompletionMessage) -> dict:
        if response.tool_calls:
            raw = response.tool_calls[0].function.arguments
        else:
            raw = (response.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if raw.startswith("submit_review"):
                raw = raw[len("submit_review") :].strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = json_repair.loads(raw)
        if isinstance(parsed, list):
            parsed = {"note_reviews": parsed}
        parsed.setdefault("coverage_gaps", [])
        parsed.setdefault("redundancy_issues", [])
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
                    role="assistant",
                    content=response.content,
                    tool_calls=[fixed],
                )
            )
            self._history.append(
                Message(
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False),
                    tool_call_id=tool_call.id,
                )
            )
        else:
            self._history.append(
                Message(role="assistant", content=response.content or "")
            )

    @staticmethod
    def _missing_review_fallback(pair_id: str) -> NoteReview:
        missing = "评审模型多次未返回该研究笔记的评估。"
        return NoteReview(
            pair_id=pair_id,
            relevance=CriterionReview(passed=True, evidence=missing),
            depth=CriterionReview(passed=False, evidence=missing),
            citations=CriterionReview(passed=False, evidence=missing),
            sources=CriterionReview(passed=False, evidence=missing),
            completeness=CriterionReview(
                passed=False,
                evidence=(
                    "该条目不能静默丢失，必须保留并重新研究后再次评审。"
                ),
            ),
            verdict="retry",
            retry_feedback=(
                "评审结果连续缺失；保留该任务并重新研究，不能清空 pending。"
            ),
        )
