from __future__ import annotations

import logging
import operator

from typing import Annotated, Callable, TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from iceberg_research.agents import Diver, Sonar, Navigator, Synthesizer
from iceberg_research.agents.planning_models import SubQuestion
from iceberg_research.agents.sonar_models import (
    CriterionReview,
    NoteReview,
    ReviewItem,
    ReviewResult,
)
from iceberg_research.base import LLMClient
from iceberg_research.memory import MemoryManager
from iceberg_research.rag.pipeline import Pipeline


logger = logging.getLogger(__name__)


def pending_sonar_reducer(existing: list, new: list) -> list:
    # An empty list is an explicit acknowledgement that every pending item
    # received either a valid review or a conservative retry fallback.
    if not new:
        return []
    return existing + new


def merge_dicts(left: dict, right: dict) -> dict:
    return {**(left or {}), **(right or {})}


class State(TypedDict):
    research_brief: str
    session_id: str | None
    sub_questions: list[SubQuestion]
    sonar_result: dict
    approved_items: Annotated[list[ReviewItem], operator.add]
    pending_sonar_items: Annotated[list[ReviewItem], pending_sonar_reducer]
    refine_round: int
    final_report: str
    retry_items: list[dict]
    sonar_summary: list[dict]
    missing_dimensions: str
    tool_call_counts: Annotated[dict, merge_dicts]


class InputSchema(TypedDict):
    research_brief: str
    session_id: str | None


class OutputSchema(TypedDict):
    final_report: str


def build_graph(
    navigator: Navigator,
    sonar: Sonar,
    create_diver: Callable[[str], Diver],
    synthesizer: Synthesizer,
    pipeline: Pipeline,
    max_rounds: int = 3,
    memory_manager: MemoryManager | None = None,
    llm_client: LLMClient | None = None,
):
    builder = StateGraph(
        State,
        input_schema=InputSchema,
        output_schema=OutputSchema,
    )

    def hand_out_subquestion(state: State):
        total = len(state["sub_questions"])
        return [
            Send(
                "diver_node",
                {
                    "sub_question_id": question.id,
                    "sub_question": question.question,
                    "note_feedback": "",
                    "diver_id": f"D-{index + 1}/{total}",
                    "attempt": 1,
                },
            )
            for index, question in enumerate(state["sub_questions"])
        ]

    def sonar_route(state: State):
        if state["refine_round"] >= max_rounds:
            logger.info("[Graph] 已达到最大评审轮数 %d，进入写作", max_rounds)
            return "synthesizer_node"

        result = ReviewResult(**state["sonar_result"])
        verdicts = {review.verdict for review in result.note_reviews}
        needs_replan = (
            "replan" in verdicts
            or bool(result.coverage_gaps)
            or bool(result.redundancy_issues)
        )
        if needs_replan:
            logger.info(
                "[Graph] Sonar 请求重规划: verdicts=%s gaps=%d redundancy=%d",
                verdicts,
                len(result.coverage_gaps),
                len(result.redundancy_issues),
            )
            return "navigator_node"

        if "retry" in verdicts:
            retry_items = state["retry_items"]
            total = len(retry_items)
            logger.info("[Graph] Sonar 请求 %d 条重试", total)
            return [
                Send(
                    "diver_node",
                    {
                        **item,
                        "diver_id": f"Retry-{index + 1}/{total}",
                    },
                )
                for index, item in enumerate(retry_items)
            ]

        logger.info("[Graph] Sonar 全部通过，进入写作")
        return "synthesizer_node"

    def navigator_node(state: State) -> dict:
        sonar_data = state.get("sonar_result")
        if sonar_data:
            questions = navigator.replan(
                research_brief=state["research_brief"],
                approved_items=state.get("approved_items", []),
                sonar_result=ReviewResult(**sonar_data),
            )
        else:
            questions = navigator.plan(state["research_brief"])
        return {"sub_questions": questions}

    def diver_node(state: dict) -> dict:
        diver_id = state.get("diver_id", "D-?")
        diver = create_diver(diver_id)
        note, tool_call_counts = diver.run(
            sub_question=state["sub_question"],
            note_feedback=state.get("note_feedback", ""),
        )
        attempt = int(state.get("attempt", 1))
        sub_question_id = state["sub_question_id"]
        item = ReviewItem(
            pair_id=f"{sub_question_id}:attempt:{attempt}",
            sub_question_id=sub_question_id,
            sub_question=state["sub_question"],
            research_note=note,
            diver_id=diver_id,
            attempt=attempt,
        )
        return {
            "pending_sonar_items": [item],
            "tool_call_counts": tool_call_counts,
        }

    def sonar_node(state: State) -> dict:
        pending = state.get("pending_sonar_items", [])
        result = sonar.review(
            research_brief=state["research_brief"],
            pending_items=pending,
            approved_items=state.get("approved_items", []),
        )

        pending_by_id = {item.pair_id: item for item in pending}
        sonar_by_id = {
            review.pair_id: review
            for review in result.note_reviews
            if review.pair_id in pending_by_id
        }
        # Sonar already guarantees fallbacks. This is a second graph-level
        # guard so pending work can never disappear due to an adapter bug.
        for pair_id in pending_by_id.keys() - sonar_by_id.keys():
            logger.error(
                "[Graph] Sonar 未返回 pair_id=%s，图层生成 retry fallback",
                pair_id,
            )
            fallback = _graph_missing_review(pair_id)
            result.note_reviews.append(fallback)
            sonar_by_id[pair_id] = fallback

        approved_items = [
            pending_by_id[review.pair_id]
            for review in result.note_reviews
            if (
                review.pair_id in pending_by_id
                and review.verdict == "approved"
            )
        ]
        retry_items = [
            {
                "sub_question_id": pending_by_id[review.pair_id].sub_question_id,
                "sub_question": pending_by_id[review.pair_id].sub_question,
                "note_feedback": (
                    review.retry_feedback or review.failed_criteria()
                ),
                "attempt": pending_by_id[review.pair_id].attempt + 1,
            }
            for review in result.note_reviews
            if review.pair_id in pending_by_id and review.verdict == "retry"
        ]
        sonar_summary = [
            {
                "pair_id": review.pair_id,
                "question": pending_by_id[review.pair_id].sub_question,
                "verdict": review.verdict,
                "failed": {
                    "relevance": not review.relevance.passed,
                    "depth": not review.depth.passed,
                    "citations": not review.citations.passed,
                    "sources": not review.sources.passed,
                    "completeness": not review.completeness.passed,
                },
                "evidence": {
                    "relevance": review.relevance.evidence,
                    "depth": review.depth.evidence,
                    "citations": review.citations.evidence,
                    "sources": review.sources.evidence,
                    "completeness": review.completeness.evidence,
                },
                "retry_feedback": review.retry_feedback,
            }
            for review in result.note_reviews
            if review.pair_id in pending_by_id
        ]
        return {
            "sonar_result": result.model_dump(),
            "approved_items": approved_items,
            "refine_round": state.get("refine_round", 0) + 1,
            "pending_sonar_items": [],
            "retry_items": retry_items,
            "sonar_summary": sonar_summary,
            "missing_dimensions": result.missing_dimensions,
        }

    def synthesizer_node(state: State) -> dict:
        result = synthesizer.run(
            research_brief=state["research_brief"],
            notes=[
                item.research_note
                for item in state.get("approved_items", [])
            ],
        )
        pipeline.add_text(text=result, query=state["research_brief"])
        if memory_manager and llm_client:
            try:
                memory_manager.remember_research(
                    llm=llm_client,
                    research_question=state["research_brief"],
                    report=result,
                    session_id=state.get("session_id"),
                )
            except Exception:
                logger.exception("[Graph] 保存长期研究记忆失败")
        return {"final_report": result}

    builder.add_node("navigator_node", navigator_node)
    builder.add_node("diver_node", diver_node)
    builder.add_node("sonar_node", sonar_node)
    builder.add_node("synthesizer_node", synthesizer_node)

    builder.add_edge(START, "navigator_node")
    builder.add_conditional_edges(
        "navigator_node",
        hand_out_subquestion,
        ["diver_node"],
    )
    builder.add_edge("diver_node", "sonar_node")
    builder.add_conditional_edges(
        "sonar_node",
        sonar_route,
        ["navigator_node", "diver_node", "synthesizer_node"],
    )
    builder.add_edge("synthesizer_node", END)
    return builder.compile()


def _graph_missing_review(pair_id: str) -> NoteReview:
    missing = "Sonar 未返回该项评审。"
    return NoteReview(
        pair_id=pair_id,
        relevance=CriterionReview(passed=True, evidence=missing),
        depth=CriterionReview(passed=False, evidence=missing),
        citations=CriterionReview(passed=False, evidence=missing),
        sources=CriterionReview(passed=False, evidence=missing),
        completeness=CriterionReview(
            passed=False,
            evidence="该 pending 项不能被清空，必须转入 retry。",
        ),
        verdict="retry",
        retry_feedback="缺少有效评审；保留任务并重新研究。",
    )
