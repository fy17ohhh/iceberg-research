from __future__ import annotations

from pydantic import BaseModel, Field


class SubQuestion(BaseModel):
    id: str = Field(
        default="",
        description="Stable short identifier unique within the research plan.",
    )
    label: str = Field(
        description="Short label (under 20 chars) capturing the core topic."
    )
    question: str = Field(description="The full self-contained research sub-question.")
    rationale: str = Field(
        description="Why this sub-question deserves separate investigation."
    )
