"""
Prompt Loader - завантаження LLM-специфічних промптів.
======================================================
Завантажує base.yaml + LLM-specific overlay (grok.yaml, gpt.yaml, gemini.yaml).

Використання:
    from src.core.prompt_loader import load_prompt, get_prompt_for_model
    
    # Завантажити для конкретної моделі
    prompt = load_prompt("grok")
    
    # Або автоматично за конфігом
    prompt = get_prompt_for_model()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Base paths
PROMPTS_DIR = Path(__file__).parent.parent.parent / "data" / "prompts"
LEGACY_PROMPT = Path(__file__).parent.parent.parent / "data" / "system_prompt_full.yaml"


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge overlay into base dict."""
    result = base.copy()
    
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """Load YAML file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Prompt file not found: %s", path)
        return {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse YAML %s: %s", path, e)
        return {}


def load_prompt(model_key: str) -> Dict[str, Any]:
    """
    Load prompt configuration for a specific model.
    
    Args:
        model_key: One of "grok", "gpt", "gemini"
    
    Returns:
        Merged prompt configuration (base + model-specific)
    """
    # Load base prompt
    base_path = PROMPTS_DIR / "base.yaml"
    base_config = load_yaml_file(base_path)
    
    if not base_config:
        logger.warning("Base prompt not found, falling back to legacy")
        return load_yaml_file(LEGACY_PROMPT)
    
    # Load model-specific overlay
    model_path = PROMPTS_DIR / f"{model_key}.yaml"
    model_config = load_yaml_file(model_path)
    
    if not model_config:
        logger.warning("Model-specific prompt not found for %s, using base only", model_key)
        return base_config
    
    # Remove 'extends' key from overlay
    model_config.pop("extends", None)
    
    # Deep merge
    merged = _deep_merge(base_config, model_config)
    
    logger.info("Loaded prompt for model: %s", model_key)
    return merged


def get_prompt_for_model(provider: Optional[str] = None) -> Dict[str, Any]:
    """
    Get prompt configuration based on current LLM provider config.
    
    Args:
        provider: Override provider (openrouter, openai, google)
    
    Returns:
        Merged prompt configuration
    """
    from src.conf.config import settings
    
    if provider is None:
        provider = settings.LLM_PROVIDER
    
    # Map provider to model key
    provider_to_key = {
        "openrouter": "grok",
        "openai": "gpt",
        "google": "gemini",
    }
    
    model_key = provider_to_key.get(provider.lower(), "grok")
    return load_prompt(model_key)


def get_system_prompt_text(model_key: str = "grok") -> str:
    """
    Generate system prompt text from configuration.
    
    Args:
        model_key: One of "grok", "gpt", "gemini"
    
    Returns:
        Formatted system prompt string
    """
    config = load_prompt(model_key)
    
    # Build prompt text from config
    parts = []
    
    # Identity
    identity = config.get("IDENTITY", {})
    if identity:
        parts.append(f"Ти {identity.get('agent_name', 'Ольга')}, {identity.get('role', 'AI-консультант')}.")
        if identity.get("personality"):
            parts.append(identity["personality"])
    
    # Rules
    rules = config.get("IMMUTABLE_RULES", [])
    if rules:
        parts.append("\nПРАВИЛА:")
        for rule in rules:
            parts.append(f"- {rule}")
    
    # Model-specific hints
    hints = config.get("REASONING_HINTS", [])
    if hints:
        parts.append("\nПІДКАЗКИ:")
        for hint in hints:
            parts.append(f"- {hint}")
    
    # Language hint
    model_specific = config.get("MODEL_SPECIFIC", {})
    if model_specific.get("language_hint"):
        parts.append(f"\n{model_specific['language_hint']}")
    
    # Output contract
    parts.append("\nФОРМАТ ВІДПОВІДІ: JSON за схемою OUTPUT_CONTRACT")
    
    return "\n".join(parts)


# Convenience functions for each model
def load_grok_prompt() -> Dict[str, Any]:
    """Load Grok-specific prompt."""
    return load_prompt("grok")


def load_gpt_prompt() -> Dict[str, Any]:
    """Load GPT-specific prompt."""
    return load_prompt("gpt")


def load_gemini_prompt() -> Dict[str, Any]:
    """Load Gemini-specific prompt."""
    return load_prompt("gemini")
