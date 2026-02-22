from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentResultV1(BaseModel):
    """Versioned intent detection contract for state metadata."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["IntentResultV1"] = "IntentResultV1"
    primary_intent: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    secondary_intents: list[str] = Field(default_factory=list)
    ambiguity: bool = False
    features_used: list[str] = Field(default_factory=list)
