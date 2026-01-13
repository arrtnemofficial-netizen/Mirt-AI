"""
Catalog Tools - Shared product search tool for agents.
======================================================
Single Source of Truth for product search functionality.
"""

from pydantic_ai import RunContext

from src.core.human_responses import get_human_response

from ..deps import AgentDeps


async def search_products_tool(
    ctx: RunContext[AgentDeps],
    query: str,
    category: str | None = None,
    *,
    include_sku: bool = False,
) -> str:
    """
    Search products in catalog.

    Use this when customer asks about product availability or wants to see products.

    Args:
        ctx: Agent context with dependencies
        query: Search query
        category: Optional category filter
        include_sku: If True, include SKU in output (for vision agent)

    Returns:
        Formatted search results
    """
    products = await ctx.deps.catalog.search_products(query, category)

    if not products:
        return get_human_response("not_found")

    lines = ["Знайдені товари:"]
    for p in products:
        name = p.get("name")
        price = p.get("price")
        sizes = ", ".join(p.get("sizes", []))
        colors = ", ".join(p.get("colors", []))

        if include_sku:
            sku = p.get("sku", "N/A")
            lines.append(f"- {name} (SKU: {sku}, {price} грн). Розміри: {sizes}. Кольори: {colors}")
        else:
            lines.append(f"- {name} ({price} грн). Розміри: {sizes}. Кольори: {colors}")

    return "\n".join(lines)
