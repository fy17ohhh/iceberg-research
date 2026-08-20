from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from pydantic import BaseModel


class ToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None

class BaseTool(ABC):
    """工具基类"""
    def __init__(self, name: str, description: str, parameters: list[ToolParameter]):
        self.name = name
        self.description = description
        self.parameters = parameters

    @abstractmethod
    def run_tool(self, parameters: dict[str, Any]) -> str:
        pass

    def to_schema(self):
        openai_schema = {
            "type": "function", 
            "function": {
                "name": self.name, 
                "description": self.description,
                "parameters": {
                    "type": "object", 
                    "properties": {}, 
                    "required": []
                }
            } 
        }
        properties = openai_schema["function"]["parameters"]["properties"]
        required = openai_schema["function"]["parameters"]["required"]

        for parameter in self.parameters:
            properties[parameter.name] = {
                "type": parameter.type, 
                "description": parameter.description
            }
            if parameter.required:
                required.append(parameter.name)

        return openai_schema


class ToolErrorCategory(str, Enum):
    """Stable error classes shared by tool adapters and agents."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ROBOTS_DENIED = "robots_denied"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    INVALID_ARGUMENT = "invalid_argument"
    NOT_FOUND = "not_found"
    EMPTY_RESULT = "empty_result"
    PARSE_ERROR = "parse_error"
    SERVER_ERROR = "server_error"
    CONCURRENCY = "concurrency"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UNKNOWN = "unknown"


class ToolRecoveryAction(str, Enum):
    """Action the agent should take after a classified tool failure."""

    RETRY_BACKOFF = "retry_with_backoff"
    FIX_ARGUMENTS = "fix_arguments"
    SWITCH_SOURCE = "switch_source"
    USE_AUTHORIZED_API = "use_authorized_api"
    BROADEN_QUERY = "broaden_or_rewrite_query"
    CHECK_CONFIGURATION = "check_configuration"
    SKIP = "skip_and_continue"


@dataclass(frozen=True)
class ToolErrorPolicy:
    category: ToolErrorCategory
    action: ToolRecoveryAction
    retryable: bool
    max_retries: int = 0
    base_delay_seconds: float = 0.0


_POLICIES = {
    ToolErrorCategory.AUTHENTICATION: ToolErrorPolicy(
        ToolErrorCategory.AUTHENTICATION,
        ToolRecoveryAction.CHECK_CONFIGURATION,
        False,
    ),
    ToolErrorCategory.AUTHORIZATION: ToolErrorPolicy(
        ToolErrorCategory.AUTHORIZATION,
        ToolRecoveryAction.USE_AUTHORIZED_API,
        False,
    ),
    ToolErrorCategory.ROBOTS_DENIED: ToolErrorPolicy(
        ToolErrorCategory.ROBOTS_DENIED,
        ToolRecoveryAction.SWITCH_SOURCE,
        False,
    ),
    ToolErrorCategory.RATE_LIMIT: ToolErrorPolicy(
        ToolErrorCategory.RATE_LIMIT,
        ToolRecoveryAction.RETRY_BACKOFF,
        True,
        max_retries=2,
        base_delay_seconds=2.0,
    ),
    ToolErrorCategory.TIMEOUT: ToolErrorPolicy(
        ToolErrorCategory.TIMEOUT,
        ToolRecoveryAction.RETRY_BACKOFF,
        True,
        max_retries=2,
        base_delay_seconds=1.0,
    ),
    ToolErrorCategory.NETWORK: ToolErrorPolicy(
        ToolErrorCategory.NETWORK,
        ToolRecoveryAction.RETRY_BACKOFF,
        True,
        max_retries=2,
        base_delay_seconds=1.0,
    ),
    ToolErrorCategory.INVALID_ARGUMENT: ToolErrorPolicy(
        ToolErrorCategory.INVALID_ARGUMENT,
        ToolRecoveryAction.FIX_ARGUMENTS,
        False,
    ),
    ToolErrorCategory.NOT_FOUND: ToolErrorPolicy(
        ToolErrorCategory.NOT_FOUND,
        ToolRecoveryAction.SWITCH_SOURCE,
        False,
    ),
    ToolErrorCategory.EMPTY_RESULT: ToolErrorPolicy(
        ToolErrorCategory.EMPTY_RESULT,
        ToolRecoveryAction.BROADEN_QUERY,
        False,
    ),
    ToolErrorCategory.PARSE_ERROR: ToolErrorPolicy(
        ToolErrorCategory.PARSE_ERROR,
        ToolRecoveryAction.SWITCH_SOURCE,
        False,
    ),
    ToolErrorCategory.SERVER_ERROR: ToolErrorPolicy(
        ToolErrorCategory.SERVER_ERROR,
        ToolRecoveryAction.RETRY_BACKOFF,
        True,
        max_retries=2,
        base_delay_seconds=1.0,
    ),
    ToolErrorCategory.CONCURRENCY: ToolErrorPolicy(
        ToolErrorCategory.CONCURRENCY,
        ToolRecoveryAction.RETRY_BACKOFF,
        True,
        max_retries=3,
        base_delay_seconds=0.5,
    ),
    ToolErrorCategory.UPSTREAM_UNAVAILABLE: ToolErrorPolicy(
        ToolErrorCategory.UPSTREAM_UNAVAILABLE,
        ToolRecoveryAction.SWITCH_SOURCE,
        False,
    ),
    ToolErrorCategory.UNKNOWN: ToolErrorPolicy(
        ToolErrorCategory.UNKNOWN,
        ToolRecoveryAction.SKIP,
        False,
    ),
}


def classify_tool_error(message: str) -> ToolErrorPolicy:
    """Classify provider-specific free text into one recovery policy."""

    normalized = message.lower()
    status_match = re.search(r"\b(?:status|http(?: status)?)\D{0,8}([1-5]\d{2})\b", normalized)
    status_code = int(status_match.group(1)) if status_match else None

    if "robots.txt" in normalized or "autonomous fetching is not allowed" in normalized:
        return _POLICIES[ToolErrorCategory.ROBOTS_DENIED]
    if "already borrowed" in normalized or "resource busy" in normalized:
        return _POLICIES[ToolErrorCategory.CONCURRENCY]
    if status_code == 429 or any(
        marker in normalized
        for marker in ("rate limit", "too many requests", "quota exceeded")
    ):
        return _POLICIES[ToolErrorCategory.RATE_LIMIT]
    if status_code == 401 or any(
        marker in normalized
        for marker in ("invalid api key", "unauthenticated", "authentication failed")
    ):
        return _POLICIES[ToolErrorCategory.AUTHENTICATION]
    if status_code == 403 or any(
        marker in normalized
        for marker in ("permission denied", "access denied", "not authorized", "forbidden")
    ):
        return _POLICIES[ToolErrorCategory.AUTHORIZATION]
    if any(
        marker in normalized
        for marker in ("timed out", "timeout", "deadline exceeded")
    ):
        return _POLICIES[ToolErrorCategory.TIMEOUT]
    if any(
        marker in normalized
        for marker in (
            "connection reset",
            "connection refused",
            "failed to connect",
            "name resolution",
            "dns",
            "network is unreachable",
        )
    ):
        return _POLICIES[ToolErrorCategory.NETWORK]
    if status_code == 404 or "not found" in normalized:
        return _POLICIES[ToolErrorCategory.NOT_FOUND]
    if status_code is not None and 500 <= status_code <= 599:
        return _POLICIES[ToolErrorCategory.SERVER_ERROR]
    if any(
        marker in normalized
        for marker in (
            "missing required parameter",
            "invalid argument",
            "invalid parameter",
            "validation error",
        )
    ):
        return _POLICIES[ToolErrorCategory.INVALID_ARGUMENT]
    if any(
        marker in normalized
        for marker in ("json decode", "parse error", "malformed response", "invalid json")
    ):
        return _POLICIES[ToolErrorCategory.PARSE_ERROR]
    if any(
        marker in normalized
        for marker in ("no results found", "empty result", "returned no results")
    ):
        return _POLICIES[ToolErrorCategory.EMPTY_RESULT]
    return _POLICIES[ToolErrorCategory.UNKNOWN]


class ToolCallError(Exception):
    def __init__(
        self,
        message: str,
        tool_name: str = "",
        *,
        category: ToolErrorCategory | None = None,
        action: ToolRecoveryAction | None = None,
        retryable: bool | None = None,
        max_retries: int | None = None,
        base_delay_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        policy = classify_tool_error(message)
        self.category = category or policy.category
        self.action = action or policy.action
        self.retryable = policy.retryable if retryable is None else retryable
        self.max_retries = policy.max_retries if max_retries is None else max_retries
        self.base_delay_seconds = (
            policy.base_delay_seconds
            if base_delay_seconds is None
            else base_delay_seconds
        )

    @classmethod
    def from_exception(
        cls, error: Exception, tool_name: str = ""
    ) -> "ToolCallError":
        if isinstance(error, cls):
            if tool_name and not error.tool_name:
                error.tool_name = tool_name
            return error
        return cls(str(error), tool_name=tool_name)

    def retry_delay(self, attempt: int) -> float:
        return min(self.base_delay_seconds * (2 ** max(attempt, 0)), 8.0)

    def to_feedback(self) -> str:
        return (
            "[TOOL_ERROR]\n"
            f"tool={self.tool_name or 'unknown'}\n"
            f"category={self.category.value}\n"
            f"recovery_action={self.action.value}\n"
            f"retryable={str(self.retryable).lower()}\n"
            f"message={self}"
        )
