"""
Payment Prompts - Shared payment-related prompt injection.
==========================================================
Single Source of Truth for payment requisites injection.
"""

from pydantic_ai import RunContext

from src.conf.payment_config import format_requisites_multiline

from ..deps import AgentDeps


async def add_payment_requisites(ctx: RunContext[AgentDeps]) -> str:
    """
    Inject canonical payment requisites to avoid LLM hallucinations.

    This is a dynamic system prompt that adds payment details.
    Used by both support_agent and payment_agent.
    """
    # НЕ показуй технічні заголовки клієнту - просто реквізити
    return format_requisites_multiline()
