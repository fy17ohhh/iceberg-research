from typing import Any

import pytest

from iceberg_research.agents.diver import Diver
from iceberg_research.tools import (
    BaseTool,
    ToolCallError,
    ToolErrorCategory,
    ToolParameter,
    ToolRecoveryAction,
    classify_tool_error,
)


@pytest.mark.parametrize(
    ("message", "category", "action", "retryable"),
    [
        (
            "When fetching robots.txt (https://example.com/robots.txt), "
            "received status 403 so autonomous fetching is not allowed",
            ToolErrorCategory.ROBOTS_DENIED,
            ToolRecoveryAction.SWITCH_SOURCE,
            False,
        ),
        (
            "HTTP status 429: too many requests",
            ToolErrorCategory.RATE_LIMIT,
            ToolRecoveryAction.RETRY_BACKOFF,
            True,
        ),
        (
            "request timed out after 30 seconds",
            ToolErrorCategory.TIMEOUT,
            ToolRecoveryAction.RETRY_BACKOFF,
            True,
        ),
        (
            "HTTP status 401: invalid API key",
            ToolErrorCategory.AUTHENTICATION,
            ToolRecoveryAction.CHECK_CONFIGURATION,
            False,
        ),
        (
            "missing required parameter 'query'",
            ToolErrorCategory.INVALID_ARGUMENT,
            ToolRecoveryAction.FIX_ARGUMENTS,
            False,
        ),
        (
            "No results found for query 'overly narrow query'",
            ToolErrorCategory.EMPTY_RESULT,
            ToolRecoveryAction.BROADEN_QUERY,
            False,
        ),
        (
            "HTTP status 503: service unavailable",
            ToolErrorCategory.SERVER_ERROR,
            ToolRecoveryAction.RETRY_BACKOFF,
            True,
        ),
    ],
)
def test_classifies_tool_errors(message, category, action, retryable):
    policy = classify_tool_error(message)

    assert policy.category == category
    assert policy.action == action
    assert policy.retryable is retryable


class SequenceTool(BaseTool):
    def __init__(self, outcomes: list[Any]):
        super().__init__(
            name="sequence_tool",
            description="test tool",
            parameters=[ToolParameter(name="query", type="string", description="q")],
        )
        self.outcomes = iter(outcomes)
        self.calls = 0

    def run_tool(self, parameters: dict[str, Any]) -> str:
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _bare_diver() -> Diver:
    diver = Diver.__new__(Diver)
    diver.name = "test"
    return diver


def test_retries_transient_errors_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "iceberg_research.agents.diver.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    tool = SequenceTool(
        [
            ToolCallError("request timed out", tool_name="sequence_tool"),
            ToolCallError("request timed out", tool_name="sequence_tool"),
            "success",
        ]
    )

    result = _bare_diver()._run_tool_with_recovery(tool, {"query": "x"})

    assert result == "success"
    assert tool.calls == 3
    assert sleeps == [1.0, 2.0]


def test_does_not_retry_robots_denial(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "iceberg_research.agents.diver.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    tool = SequenceTool(
        [
            ToolCallError(
                "robots.txt received status 403; autonomous fetching is not allowed",
                tool_name="sequence_tool",
            ),
            "should not be reached",
        ]
    )

    with pytest.raises(ToolCallError) as caught:
        _bare_diver()._run_tool_with_recovery(tool, {"query": "x"})

    assert caught.value.category == ToolErrorCategory.ROBOTS_DENIED
    assert caught.value.action == ToolRecoveryAction.SWITCH_SOURCE
    assert tool.calls == 1
    assert sleeps == []


def test_error_feedback_is_machine_readable():
    error = ToolCallError(
        "No results found for query 'x'",
        tool_name="search",
    )

    feedback = error.to_feedback()

    assert "category=empty_result" in feedback
    assert "recovery_action=broaden_or_rewrite_query" in feedback
    assert "retryable=false" in feedback
