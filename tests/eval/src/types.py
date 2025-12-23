"""Type definitions for Prompt Evaluation Framework.
Matches TypeScript types from eval architecture design.
Uses centralized state/intent definitions to avoid duplication.
"""

from typing import Literal

from pydantic import BaseModel

# Import from centralized state machine to avoid duplication
from src.core.state_machine import Intent, State


# Type aliases for evaluation compatibility - unpack tuple for Literal
MirtState = Literal[*tuple(State.__members__.keys())]
MirtIntent = Literal[*tuple(Intent.__members__.keys())]


class Product(BaseModel):
    id: str
    name: str
    size: str | None = None
    color: str | None = None
    price: float | None = None
    photo_url: str | None = None


class OutputMetadata(BaseModel):
    session_id: str
    current_state: MirtState
    intent: MirtIntent
    escalation_level: Literal["L0", "L1", "L2"] | None = None
    reasoning: str | None = None


class Message(BaseModel):
    text: str


class MirtOutputContract(BaseModel):
    """Strict output contract for MIRT AI."""

    messages: list[Message]
    products: list[Product]
    metadata: OutputMetadata


# --- TEST CASE TYPES ---


class TestInputMetadata(BaseModel):
    current_state: str | None = None
    channel: str
    language: str


class TestInput(BaseModel):
    session_id: str | None
    text: str | None
    image_url: str | None = None
    metadata: TestInputMetadata


class TestRules(BaseModel):
    must_have_products: bool = False
    max_products: int = 0
    min_products: int | None = 0
    must_ask_clarifying: bool | None = False


class TestSafety(BaseModel):
    forbid_escalation: bool | None = False
    forbid_admin_reasons: list[str] | None = None
    forbid_internal_leak: bool | None = None
    forbid_competitors: bool | None = None
    forbid_prices_without_tools: bool | None = None


class TestTone(BaseModel):
    should_feel: list[str]


class TestExpected(BaseModel):
    intent: MirtIntent
    min_state: str | None = None
    allowed_states: list[str]
    must_not_state: list[str] = []
    rules: TestRules
    safety: TestSafety = TestSafety()
    tone_hints: TestTone | None = None


class TestCase(BaseModel):
    id: str
    description: str
    input: TestInput
    expected: TestExpected


# --- CONFIG TYPES ---


class ModelAPI(BaseModel):
    type: Literal["openai", "google_ai"]  # openrouter removed
    base_url: str
    model_name: str
    api_key_env: str


class ReasoningConfig(BaseModel):
    mode: Literal["none", "low", "medium", "high"]
    adaptive: bool | None = False
    max_tokens: int | None = 4096


class ModelConfig(BaseModel):
    id: str
    role: Literal["assistant_under_test", "llm_judge"]
    provider: Literal["xai", "google", "openai"]
    api: ModelAPI
    reasoning: ReasoningConfig | None = None


class ModelsConfig(BaseModel):
    models: list[ModelConfig]


class TestSuite(BaseModel):
    version: str
    project: str
    target_states: list[str] = []
    tests: list[TestCase]
