"""
Prompt Loader - завантаження LLM-специфічних промптів.
======================================================
Завантажує base.yaml + LLM-specific overlay (grok.yaml, gpt.yaml, gemini.yaml).

Використання:
    from src.core.prompt_loader import load_prompt, get_system_prompt_text
    
    # Завантажити конфіг для моделі
    config = load_prompt("grok")
    
    # Отримати готовий system prompt text
    text = get_system_prompt_text("grok")
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
    
    Merges in this order (later overrides earlier):
    1. system_prompt_full.yaml (legacy full prompt with all sections)
    2. base.yaml (simplified base)
    3. model-specific yaml (grok.yaml, gpt.yaml, gemini.yaml)
    
    Args:
        model_key: One of "grok", "gpt", "gemini"
    
    Returns:
        Merged prompt configuration with ALL sections
    """
    # 1. Start with legacy full prompt (has all the critical sections!)
    full_config = load_yaml_file(LEGACY_PROMPT)
    
    # 2. Load base prompt (simplified structure)
    base_path = PROMPTS_DIR / "base.yaml"
    base_config = load_yaml_file(base_path)
    
    # Merge base into full (base overrides full where specified)
    if base_config:
        merged = _deep_merge(full_config, base_config)
    else:
        merged = full_config
    
    # 3. Load model-specific overlay
    model_path = PROMPTS_DIR / f"{model_key}.yaml"
    model_config = load_yaml_file(model_path)
    
    if model_config:
        # Remove 'extends' key from overlay
        model_config.pop("extends", None)
        # Model-specific overrides everything
        merged = _deep_merge(merged, model_config)
    
    logger.info("Loaded prompt for model: %s (sections: %s)", model_key, list(merged.keys()))
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
    Generate system prompt text from configuration using Pydantic model.
    
    Args:
        model_key: One of "grok", "gpt", "gemini"
    
    Returns:
        Formatted system prompt string optimized for the target LLM.
    """
    from src.core.prompt_config import PromptConfig
    
    config_dict = load_prompt(model_key)
    config = PromptConfig.from_dict(config_dict)
    return config.to_system_prompt()


def get_prompt_config(model_key: str = "grok") -> "PromptConfig":
    """
    Load and validate prompt configuration as Pydantic model.
    
    Args:
        model_key: One of "grok", "gpt", "gemini"
    
    Returns:
        Validated PromptConfig instance
    """
    from src.core.prompt_config import PromptConfig
    
    config_dict = load_prompt(model_key)
    return PromptConfig.from_dict(config_dict)


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
