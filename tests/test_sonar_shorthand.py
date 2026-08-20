from iceberg_search.agents.sonar_models import NoteReview

def test_note_review_normalizes_shorthand_criterion_statuses():
    review = NoteReview(
        pair_id="pair-short",
        relevance="passed",
        depth="passed",
        citations=True,
        sources={"passed": "true", "evidence": "multiple sources"},
        completeness="failed",
        verdict="approved",
    )

    assert review.relevance.passed is True
    assert review.depth.passed is True
    assert review.citations.passed is True
    assert review.sources.passed is True
    assert review.completeness.passed is False
    assert review.completeness.evidence
    assert review.verdict == "retry"


def test_criterion_review_rejects_unknown_shorthand_status():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Unsupported criterion status"):
        NoteReview(
            pair_id="pair-unknown",
            relevance="maybe",
            depth="passed",
            citations="passed",
            sources="passed",
            completeness="passed",
            verdict="approved",
        )
