import json
import re

from openai.types.chat import ChatCompletionMessage

from iceberg_research.agents.sonar import Sonar
from iceberg_research.agents.sonar_models import (
    CriterionReview,
    NoteReview,
    ReviewItem,
)


class FakeContextBuilder:
    def build_context(self, system_prompt, history):
        return [{"role": item.role, "content": item.content} for item in history]


def _criterion(passed=True, evidence="evidence"):
    return {"passed": passed, "evidence": evidence}


def _approved(pair_id):
    return {
        "pair_id": pair_id,
        "relevance": _criterion(),
        "depth": _criterion(),
        "citations": _criterion(),
        "sources": _criterion(),
        "completeness": _criterion(),
        "verdict": "approved",
        "retry_feedback": "",
    }


class FakeLLM:
    def __init__(self, review_counts):
        self.review_counts = iter(review_counts)
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        pair_ids = re.findall(r'<review_item pair_id="([^"]+)">', prompt)
        count = next(self.review_counts)
        return ChatCompletionMessage(
            role="assistant",
            content=json.dumps(
                {
                    "note_reviews": [
                        _approved(pair_id) for pair_id in pair_ids[:count]
                    ],
                    "coverage_gaps": [],
                    "redundancy_issues": [],
                }
            ),
        )


def _items(count):
    return [
        ReviewItem(
            pair_id=f"sq_{index}:attempt:1",
            sub_question_id=f"sq_{index}",
            sub_question=f"question-{index}",
            research_note=f"note-{index}",
            diver_id=f"D-{index}",
        )
        for index in range(count)
    ]


def test_sonar_batches_and_retries_only_missing_pair_ids():
    llm = FakeLLM([1, 1, 2])
    sonar = Sonar(
        llm=llm,
        context_builder=FakeContextBuilder(),
        batch_size=2,
        max_attempts=3,
    )

    result = sonar.review("brief", _items(4))

    assert [review.pair_id for review in result.note_reviews] == [
        "sq_0:attempt:1",
        "sq_1:attempt:1",
        "sq_2:attempt:1",
        "sq_3:attempt:1",
    ]
    assert len(llm.calls) == 3
    requested_sizes = [
        call["tools"][0]["function"]["parameters"]["properties"]["note_reviews"][
            "minItems"
        ]
        for call in llm.calls
    ]
    assert requested_sizes == [2, 1, 2]


def test_sonar_marks_missing_results_retry_after_attempt_limit():
    llm = FakeLLM([0, 0, 0])
    sonar = Sonar(
        llm=llm,
        context_builder=FakeContextBuilder(),
        batch_size=4,
        max_attempts=3,
    )

    result = sonar.review("brief", _items(4))

    assert len(result.note_reviews) == 4
    assert {review.verdict for review in result.note_reviews} == {"retry"}
    assert all(
        "不能静默丢失" in review.completeness.evidence
        for review in result.note_reviews
    )


def test_sonar_call_failures_do_not_abort_pipeline():
    class FailingLLM:
        def invoke(self, **kwargs):
            raise RuntimeError("temporary provider error")

    sonar = Sonar(
        llm=FailingLLM(),
        context_builder=FakeContextBuilder(),
        batch_size=2,
        max_attempts=2,
    )

    result = sonar.review("brief", _items(2))

    assert [review.verdict for review in result.note_reviews] == [
        "retry",
        "retry",
    ]


def test_note_review_enforces_decision_tree():
    review = NoteReview(
        pair_id="pair-1",
        relevance=CriterionReview(passed=False, evidence="off topic"),
        depth=CriterionReview(passed=True, evidence="deep"),
        citations=CriterionReview(passed=True, evidence="cited"),
        sources=CriterionReview(passed=True, evidence="diverse"),
        completeness=CriterionReview(passed=True, evidence="complete"),
        verdict="approved",
    )
    assert review.verdict == "replan"

    sources_only = NoteReview(
        pair_id="pair-2",
        relevance=CriterionReview(passed=True, evidence="relevant"),
        depth=CriterionReview(passed=True, evidence="deep"),
        citations=CriterionReview(passed=True, evidence="cited"),
        sources=CriterionReview(passed=False, evidence="only two"),
        completeness=CriterionReview(passed=True, evidence="complete"),
        verdict="retry",
    )
    assert sources_only.verdict == "approved"
