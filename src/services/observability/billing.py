"""
Billing Service.
================

Centralized logic for financial calculations, pricing configurations, 
and currency conversions (USD <-> UAH).

This module is the Single Source of Truth (SSOT) for:
- Model Pricing (per 1M tokens)
- Exchange Rates
- Cost Calculation Logic
"""

from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# =============================================================================
# PRICING CONFIGURATION (SSOT)
# =============================================================================

# Pricing per 1M tokens (USD)
# Updated 2026-01-11
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    # Custom/Configured models
    "gpt-5.1": {"input": Decimal("1.25"), "output": Decimal("10.00")},  
    "gpt-5.1-mini": {"input": Decimal("0.25"), "output": Decimal("1.00")}, # Estimated
    
    # Legacy/Standard models
    "gpt-4o": {"input": Decimal("2.50"), "output": Decimal("10.00")},
    "gpt-4o-mini": {"input": Decimal("0.15"), "output": Decimal("0.60")},
    "gpt-4-turbo": {"input": Decimal("10.00"), "output": Decimal("30.00")},
    "gpt-4": {"input": Decimal("30.00"), "output": Decimal("60.00")},
    "gpt-3.5-turbo": {"input": Decimal("0.50"), "output": Decimal("1.50")},
    "claude-3-5-sonnet": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "claude-3-5-haiku": {"input": Decimal("0.25"), "output": Decimal("1.25")},
    
    # Default fallback
    "default": {"input": Decimal("1.00"), "output": Decimal("3.00")},
}

EXCHANGE_RATE_UAH = Decimal("43.17")


# =============================================================================
# CALCULATION LOGIC
# =============================================================================

def calculate_cost(
    model: str,
    tokens_input: int,
    tokens_output: int,
) -> tuple[Decimal, Decimal]:
    """Calculate cost in USD and UAH for token usage.

    Args:
        model: Model name
        tokens_input: Input token count
        tokens_output: Output token count

    Returns:
        Tuple of (cost_usd, cost_uah) as Decimals
    """
    # Normalize model name slightly to catch versions
    pricing = None
    for key in MODEL_PRICING:
        if key in model:
            pricing = MODEL_PRICING[key]
            break
    
    if not pricing:
        pricing = MODEL_PRICING["default"]

    # Calculate cost (pricing is per 1M tokens)
    input_cost = (Decimal(tokens_input) / Decimal(1_000_000)) * pricing["input"]
    output_cost = (Decimal(tokens_output) / Decimal(1_000_000)) * pricing["output"]

    cost_usd = (input_cost + output_cost).quantize(Decimal("0.000001"))
    cost_uah = (cost_usd * EXCHANGE_RATE_UAH).quantize(Decimal("0.0001"))
    
    return cost_usd, cost_uah
