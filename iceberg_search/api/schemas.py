from __future__ import annotations

from typing import Literal
from pydantic import BaseModel
from iceberg_search.memory.models import ResearchPreferences


class NavigationRequest(BaseModel):
    query: str


class NavigationResult(BaseModel):
    is_clear: bool
    brief: str | None = None
    directions: list[str] = []
    message: str | None = None


class NavigationRefineRequest(BaseModel):
    query: str
    response: str


class NavigationRefineResult(BaseModel):
    brief: str


class ResearchRequest(BaseModel):
    brief: str
    session_id: str | None = None


class SaveReportRequest(BaseModel):
    title: str
    content: str


class IngestRequest(BaseModel):
    src: str
    custom_title: str | None = None
    overwrite: bool = True


class IngestResult(BaseModel):
    title: str
    status: Literal["skipped", "overwritten", "created"]


class PreferencesRequest(BaseModel):
    preferences: ResearchPreferences
    session_id: str | None = None
