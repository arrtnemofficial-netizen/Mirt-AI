"""Type definitions for Prompt Evaluation Framework.
Matches TypeScript types from eval architecture design.
"""
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


# --- CORE TYPES ---

MirtState = Literal[
    "STATE_0_INIT",
    "STATE_1_DISCOVERY",
    "STATE_2_VISION",
    "STATE_3_SIZE_COLOR",
    "STATE_5_PAYMENT_DELIVERY",
    "STATE_6_UPSELL",
    "STATE_7_END",
    "STATE_8_COMPLAINT",
    "STATE_9_OOD",
]

MirtIntent = Literal[
    "GREETING_ONLY",
    "DISCOVERY_OR_QUESTION",
    "PHOTO_IDENT",
    "SIZE_HELP",
    "COLOR_HELP",
    "PAYMENT_DELIVERY",
    "COMPLAINT",
    "THANKYOU_SMALLTALK",
    "OUT_OF_DOMAIN",
    "UNKNOWN_OR_EMPTY",
]

class Product(BaseModel):
    id: str
    name: str
    size: Optional[str] = None
    color: Optional[str] = None
    price: Optional[float] = None
    photo_url: Optional[str] = None

class OutputMetadata(BaseModel):
    session_id: str
    current_state: MirtState
    intent: MirtIntent
    escalation_level: Optional[Literal["L0", "L1", "L2"]] = None
    reasoning: Optional[str] = None

class Message(BaseModel):
    text: str

class MirtOutputContract(BaseModel):
    """Strict output contract for MIRT AI."""
    messages: List[Message]
    products: List[Product]
    metadata: OutputMetadata


# --- TEST CASE TYPES ---

class TestInputMetadata(BaseModel):
    current_state: Optional[str] = None
    channel: str
    language: str

class TestInput(BaseModel):
    session_id: Optional[str]
    text: Optional[str]
    image_url: Optional[str] = None
    metadata: TestInputMetadata

class TestRules(BaseModel):
    must_have_products: bool = False
    max_products: int = 0
    min_products: Optional[int] = 0
    must_ask_clarifying: Optional[bool] = False

class TestSafety(BaseModel):
    forbid_escalation: Optional[bool] = False
    forbid_admin_reasons: Optional[List[str]] = None
    forbid_internal_leak: Optional[bool] = None
    forbid_competitors: Optional[bool] = None
    forbid_prices_without_tools: Optional[bool] = None

class TestTone(BaseModel):
    should_feel: List[str]

class TestExpected(BaseModel):
    intent: MirtIntent
    min_state: Optional[str] = None
    allowed_states: List[str]
    must_not_state: List[str] = []
    rules: TestRules
    safety: TestSafety = TestSafety()
    tone_hints: Optional[TestTone] = None

class TestCase(BaseModel):
    id: str
    description: str
    input: TestInput
    expected: TestExpected


# --- CONFIG TYPES ---

class ModelAPI(BaseModel):
    type: Literal["openai", "google_ai", "openrouter"]
    base_url: str
    model_name: str
    api_key_env: str

class ReasoningConfig(BaseModel):
    mode: Literal["none", "low", "medium", "high"]
    adaptive: Optional[bool] = False
    max_tokens: Optional[int] = 4096

class ModelConfig(BaseModel):
    id: str
    role: Literal["assistant_under_test", "llm_judge"]
    provider: Literal["xai", "google", "openai"]
    api: ModelAPI
    reasoning: Optional[ReasoningConfig] = None

class ModelsConfig(BaseModel):
    models: List[ModelConfig]

class TestSuite(BaseModel):
    version: str
    project: str
    target_states: List[str] = []
    tests: List[TestCase]
