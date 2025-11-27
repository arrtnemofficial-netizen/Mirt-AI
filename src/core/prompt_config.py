"""
Pydantic models for LLM prompt configuration.
=============================================
Typed configuration models that match base.yaml + LLM-specific overlays.
Used for validation and IDE autocompletion.

Usage:
    from src.core.prompt_config import PromptConfig
    config = PromptConfig.from_yaml("grok")
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MetaConfig(BaseModel):
    """Metadata about the prompt configuration."""
    
    version: str = "6.1"
    project: str = "MIRT - дитячий одяг"
    language_out: str = "uk"
    timezone: str = "Europe/Kyiv"
    hallucination_tolerance: Literal["ZERO", "LOW", "MEDIUM"] = "ZERO"
    safety_priority: Literal["MAXIMUM", "HIGH", "MEDIUM"] = "MAXIMUM"
    max_response_chars: int = 900
    target_model: Optional[str] = None
    reasoning_mode: Optional[str] = None
    provider: Optional[str] = None


class IdentityConfig(BaseModel):
    """Agent identity and personality."""
    
    role: str = "AI-консультант магазину дитячого одягу MIRT"
    agent_name: str = "Ольга"
    personality: str = ""
    mission: str = ""
    domain: str = "Дитячий одяг MIRT (сукні, костюми, тренчі)"
    language: str = "Українська"


class ModelSpecificConfig(BaseModel):
    """LLM-specific optimizations."""
    
    temperature: float = Field(default=0.3, ge=0, le=1)
    max_tokens: int = Field(default=2048, gt=0)
    language_hint: Optional[str] = None
    verbosity: Literal["concise", "moderate", "verbose"] = "concise"
    tool_format: str = "openai_compatible"


class ResponseStyleConfig(BaseModel):
    """Response formatting preferences."""
    
    greeting_style: str = "warm_casual"
    explanation_depth: Literal["minimal", "moderate", "detailed"] = "minimal"
    emoji_usage: Literal["none", "minimal", "moderate", "heavy"] = "moderate"


class VisionConfig(BaseModel):
    """Vision/image analysis configuration."""
    
    enabled: bool = False
    photo_analysis_prompt: Optional[str] = None


class PromptConfig(BaseModel):
    """
    Complete prompt configuration for a specific LLM.
    
    Combines base.yaml + model-specific overlay (grok/gpt/gemini).
    Used for:
    - Validation at load time
    - Type-safe access in code
    - System prompt generation
    """
    
    META: MetaConfig = Field(default_factory=MetaConfig)
    IDENTITY: IdentityConfig = Field(default_factory=IdentityConfig)
    MODEL_SPECIFIC: ModelSpecificConfig = Field(default_factory=ModelSpecificConfig)
    RESPONSE_STYLE: ResponseStyleConfig = Field(default_factory=ResponseStyleConfig)
    VISION: VisionConfig = Field(default_factory=VisionConfig)
    
    IMMUTABLE_RULES: List[str] = Field(default_factory=list)
    REASONING_HINTS: List[str] = Field(default_factory=list)
    GUARDRAILS: List[str] = Field(default_factory=list)
    
    STATE_DESCRIPTIONS: Dict[str, Any] = Field(default_factory=dict)  # Include output_templates!
    INTENT_LABELS: List[str] = Field(default_factory=list)
    INTENT_CLASSIFICATION_RULES: Dict[str, Any] = Field(default_factory=dict)
    OUTPUT_CONTRACT: Dict[str, Any] = Field(default_factory=dict)
    
    # Critical sections from system_prompt_full.yaml
    DATABASE_SCHEMA: Dict[str, Any] = Field(default_factory=dict)
    TOOLS: Dict[str, Any] = Field(default_factory=dict)
    REASONING_KERNEL: Dict[str, Any] = Field(default_factory=dict)
    SIZE_MAPPING: Dict[str, Any] = Field(default_factory=dict)
    PRICING_POLICY: Dict[str, Any] = Field(default_factory=dict)
    VISION_RULES: Dict[str, Any] = Field(default_factory=dict)
    VISION_PHRASING: Dict[str, Any] = Field(default_factory=dict)
    INTERACTION_PRINCIPLES: Dict[str, Any] = Field(default_factory=dict)
    BANS_STRICT: List[str] = Field(default_factory=list)
    PRE_OUTPUT_CHECKLIST: Dict[str, Any] = Field(default_factory=dict)
    CONVERSATION_RECOVERY: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptConfig":
        """Create config from merged YAML dict."""
        return cls.model_validate(data)
    
    def to_system_prompt(self) -> str:
        """
        Generate COMPLETE system prompt text for LLM.
        Includes all critical sections: states with templates, size mapping, etc.
        
        Returns:
            Formatted system prompt string optimized for the target LLM.
        """
        import yaml
        parts: List[str] = []
        
        # 1. Identity block
        parts.append(f"# РОЛЬ: {self.IDENTITY.agent_name}")
        parts.append(f"Ти {self.IDENTITY.agent_name}, {self.IDENTITY.role}.")
        if self.IDENTITY.personality:
            parts.append(self.IDENTITY.personality.strip())
        if self.IDENTITY.mission:
            parts.append(f"\nМІСІЯ: {self.IDENTITY.mission.strip()}")
        
        # 2. Immutable rules
        if self.IMMUTABLE_RULES:
            parts.append("\n# ЗАЛІЗНІ ПРАВИЛА (порушення = провал)")
            for i, rule in enumerate(self.IMMUTABLE_RULES, 1):
                parts.append(f"{i}. {rule}")
        
        # 3. STATE_DESCRIPTIONS with output_templates (CRITICAL!)
        if self.STATE_DESCRIPTIONS:
            parts.append("\n# СТАНИ ДІАЛОГУ ТА ШАБЛОНИ ВІДПОВІДЕЙ")
            for state_name, state_data in self.STATE_DESCRIPTIONS.items():
                if state_name == "note":
                    continue
                if isinstance(state_data, dict):
                    desc = state_data.get("description", "")
                    parts.append(f"\n## {state_name}")
                    parts.append(f"Опис: {desc}")
                    
                    # Goals
                    if "goals" in state_data:
                        parts.append("Цілі:")
                        for goal in state_data["goals"]:
                            parts.append(f"  - {goal}")
                    
                    # Output templates - ЦЕ КРИТИЧНО!
                    if "output_templates" in state_data:
                        parts.append("Шаблони відповідей:")
                        for tpl_name, tpl_text in state_data["output_templates"].items():
                            parts.append(f"  {tpl_name}: \"{tpl_text}\"")
                    
                    # Escalation level
                    if "escalation" in state_data:
                        parts.append(f"Ескалація: {state_data['escalation']}")
                else:
                    parts.append(f"- {state_name}: {state_data}")
        
        # 4. Intent classification
        if self.INTENT_LABELS:
            parts.append("\n# КЛАСИФІКАЦІЯ INTENT")
            parts.append("Визнач intent як один з: " + ", ".join(self.INTENT_LABELS))
        
        # 5. SIZE_MAPPING - КРИТИЧНО!
        if self.SIZE_MAPPING:
            parts.append("\n# РОЗМІРНА СІТКА (ЗРІСТ → РОЗМІР)")
            if "mapping" in self.SIZE_MAPPING:
                for m in self.SIZE_MAPPING["mapping"]:
                    parts.append(f"  {m.get('range_cm', '')}: {m.get('preferred_sizes', [])}")
            if "rules_general" in self.SIZE_MAPPING:
                parts.append("Правила:")
                for rule in self.SIZE_MAPPING["rules_general"]:
                    parts.append(f"  - {rule}")
        
        # 6. PRICING_POLICY
        if self.PRICING_POLICY and "rules" in self.PRICING_POLICY:
            parts.append("\n# ЦІНИ")
            for rule in self.PRICING_POLICY["rules"]:
                parts.append(f"- {rule}")
        
        # 7. VISION_RULES
        if self.VISION_RULES:
            parts.append("\n# РОБОТА З ФОТО")
            if "steps" in self.VISION_RULES:
                for step in self.VISION_RULES["steps"]:
                    parts.append(f"- {step}")
            if "ban" in self.VISION_RULES:
                parts.append("Заборонено:")
                for ban in self.VISION_RULES["ban"]:
                    parts.append(f"  - {ban}")
        
        # 8. INTERACTION_PRINCIPLES
        if self.INTERACTION_PRINCIPLES:
            parts.append("\n# ПРИНЦИПИ ВЗАЄМОДІЇ")
            for key, rules in self.INTERACTION_PRINCIPLES.items():
                if isinstance(rules, list):
                    for rule in rules:
                        parts.append(f"- {rule}")
        
        # 9. BANS
        if self.BANS_STRICT:
            parts.append("\n# СТРОГІ ЗАБОРОНИ")
            for ban in self.BANS_STRICT:
                parts.append(f"❌ {ban}")
        
        # 10. CONVERSATION_RECOVERY
        if self.CONVERSATION_RECOVERY:
            parts.append("\n# ВІДНОВЛЕННЯ РОЗМОВИ")
            for recovery_type, data in self.CONVERSATION_RECOVERY.items():
                if isinstance(data, dict) and "templates" in data:
                    parts.append(f"\n{recovery_type}:")
                    for tpl_name, tpl_text in data["templates"].items():
                        parts.append(f"  {tpl_name}: \"{tpl_text}\"")
        
        # 11. Model-specific hints
        if self.REASONING_HINTS:
            parts.append("\n# ПІДКАЗКИ ДЛЯ REASONING")
            for hint in self.REASONING_HINTS:
                parts.append(f"- {hint}")
        
        # 12. Guardrails
        if self.GUARDRAILS:
            parts.append("\n# GUARDRAILS")
            for guard in self.GUARDRAILS:
                parts.append(f"⚠️ {guard}")
        
        # 13. Language hint
        if self.MODEL_SPECIFIC.language_hint:
            parts.append(f"\n{self.MODEL_SPECIFIC.language_hint}")
        
        # 14. Output format
        parts.append("\n# ФОРМАТ ВІДПОВІДІ")
        parts.append("Відповідай ТІЛЬКИ валідним JSON за схемою:")
        parts.append(self._format_output_schema())
        
        # 15. Response constraints
        parts.append(f"\n# ОБМЕЖЕННЯ")
        parts.append(f"- Максимум {self.META.max_response_chars} символів у messages.content")
        parts.append(f"- Verbosity: {self.MODEL_SPECIFIC.verbosity}")
        parts.append(f"- Emojis: {self.RESPONSE_STYLE.emoji_usage}")
        
        return "\n".join(parts)
    
    def _format_output_schema(self) -> str:
        """Format OUTPUT_CONTRACT as readable schema for LLM."""
        return '''```json
{
  "event": "simple_answer|offer|escalation|checkout|out_of_domain",
  "messages": [{"type": "text", "content": "..."}],
  "products": [{"id": 123, "name": "...", "size": "...", "color": "...", "price": 100.0, "photo_url": "https://..."}],
  "metadata": {
    "session_id": "<copy from input>",
    "current_state": "STATE_X_NAME",
    "intent": "INTENT_LABEL",
    "escalation_level": "NONE|L1|L2|L3"
  },
  "escalation": null | {"level": "L1", "reason": "...", "target": "admin"}
}
```'''
