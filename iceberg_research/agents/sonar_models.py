from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ReviewItem(BaseModel):
    pair_id: str
    sub_question_id: str
    sub_question: str
    research_note: str
    diver_id: str
    attempt: int = Field(default=1, ge=1)


class CriterionReview(BaseModel):
    passed: bool
    evidence: str = Field(min_length=1)

    @field_validator("passed", mode="before")
    @classmethod
    def normalize_passed(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"passed", "pass", "true", "yes", "approved"}:
                return True
            if normalized in {"failed", "fail", "false", "no", "rejected"}:
                return False
        raise ValueError(f"Unsupported criterion status: {value!r}")


class NoteReview(BaseModel):
    pair_id: str
    relevance: CriterionReview
    depth: CriterionReview
    citations: CriterionReview
    sources: CriterionReview
    completeness: CriterionReview
    verdict: Literal["approved", "retry", "replan"]
    retry_feedback: str = ""

    @field_validator(
        "relevance",
        "depth",
        "citations",
        "sources",
        "completeness",
        mode="before",
    )
    @classmethod
    def normalize_criterion(cls, value: Any) -> Any:
        if isinstance(value, CriterionReview):
            return value
        if isinstance(value, (bool, str)):
            return {
                "passed": value,
                "evidence": f"Judge returned shorthand criterion status: {value!s}",
            }
        if isinstance(value, dict):
            normalized = dict(value)
            if not str(normalized.get("evidence", "")).strip():
                normalized["evidence"] = (
                    "Judge omitted criterion evidence; status was normalized at validation."
                )
            return normalized
        return value

    @model_validator(mode="after")
    def enforce_decision_tree(self):
        if not self.relevance.passed:
            expected = "replan"
        elif (
            not self.depth.passed
            or not self.citations.passed
            or not self.completeness.passed
        ):
            expected = "retry"
        else:
            expected = "approved"
        self.verdict = expected
        if expected != "approved" and not self.retry_feedback:
            self.retry_feedback = self.failed_criteria()
        return self

    def failed_criteria(self) -> str:
        failed = []
        for name in (
            "relevance",
            "depth",
            "citations",
            "sources",
            "completeness",
        ):
            criterion = getattr(self, name)
            if not criterion.passed:
                failed.append(f"{name}: {criterion.evidence}")
        if self.retry_feedback and self.retry_feedback not in "\n".join(failed):
            failed.append(f"action: {self.retry_feedback}")
        return "\n".join(failed)


class CoverageGap(BaseModel):
    dimension: str
    reason: str
    suggested_scope: str


class RedundancyIssue(BaseModel):
    pair_ids: list[str]
    overlapping_sources: list[str] = Field(default_factory=list)
    recommendation: str


class ReviewResult(BaseModel):
    note_reviews: list[NoteReview]
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    redundancy_issues: list[RedundancyIssue] = Field(default_factory=list)

    @property
    def missing_dimensions(self) -> str:
        """Compatibility string for existing API/frontend rendering."""
        return "\n".join(
            f"{gap.dimension}: {gap.reason} 建议范围: {gap.suggested_scope}"
            for gap in self.coverage_gaps
        )
