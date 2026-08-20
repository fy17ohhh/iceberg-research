from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MemoryType = Literal["user_preference", "research_context", "research_fact"]
MemoryStatus = Literal["active", "superseded", "expired", "retracted"]


class Evidence(BaseModel):
    title: str
    url: str
    source_type: Literal[
        "paper",
        "official_documentation",
        "official_report",
        "dataset",
        "webpage",
        "book",
        "news",
    ] = "webpage"
    published_at: str | None = None
    accessed_at: str
    excerpt: str | None = None


class MemoryOrigin(BaseModel):
    kind: Literal["user_message", "research_session"]
    session_id: str | None = None
    message_id: str | None = None
    excerpt: str | None = None
    research_question: str | None = None
    diver_id: str | None = None
    created_by: Literal["user", "diver", "synthesizer", "system"]


class MemoryLifecycle(BaseModel):
    status: MemoryStatus = "active"
    created_at: str
    updated_at: str
    last_verified_at: str | None = None
    expires_at: str | None = None
    supersedes: list[str] = Field(default_factory=list)


class MemoryItem(BaseModel):
    schema_version: Literal[1] = 1
    id: str
    type: MemoryType
    subject: str
    content: str
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    origin: MemoryOrigin
    lifecycle: MemoryLifecycle


class RetrievedMemory(BaseModel):
    memory: MemoryItem
    score: float


class ResearchPreferences(BaseModel):
    report_language: Literal["auto", "zh-CN", "en"] = "auto"
    report_depth: Literal["concise", "balanced", "deep"] = "deep"
    prefer_primary_sources: bool = True
    prefer_academic_sources: bool = True
    include_methodology: bool = True
    include_quantitative_evidence: bool = True
    include_code_repositories: bool = False
    research_context: str = ""

    @field_validator("research_context")
    @classmethod
    def reject_credentials(cls, value: str) -> str:
        secret_patterns = (
            r"\b(?:api[_ -]?key|access[_ -]?token|password|cookie)\s*[:=]\s*\S+",
            r"\bsk-[A-Za-z0-9_-]{16,}",
        )
        if any(re.search(pattern, value, re.IGNORECASE) for pattern in secret_patterns):
            raise ValueError("长期研究背景不能包含 API Key、Token、密码或 Cookie")
        return value
