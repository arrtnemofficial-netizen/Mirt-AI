"""
Snippet Loader - Extract snippets from snippets.md.

This module handles parsing and loading of snippets from the snippets.md file.
Extracted from vision.py for better testability and maintainability.
"""

import logging


logger = logging.getLogger(__name__)


def get_snippet_by_header(header_name: str) -> list[str] | None:
    """Get snippet by exact header name from snippets.md.

    Returns list of bubbles (split by ---) or None if not found.

    Args:
        header_name: Exact header name to search for (e.g., "Невідомий товар (ескалація)")

    Returns:
        List of bubble texts or None if not found
    """
    try:
        from src.core.prompt_registry import registry

        content = registry.get("system.snippets").content
    except Exception:
        return None

    if not content:
        return None

    # Parse snippets.md - find section with exact header
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for ### header with exact match
        if line.startswith("### ") and line[4:].strip() == header_name:
            # Found exact match! Extract the snippet body
            body_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("### "):
                body_lines.append(lines[i])
                i += 1

            # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
            text_lines = []
            for bl in body_lines:
                bl_stripped = bl.strip()
                if bl_stripped.startswith("КОЛИ:") or bl_stripped.startswith("НЕ КОЛИ:"):
                    continue
                text_lines.append(bl_stripped)

            # Join and split by ---
            full_text = "\n".join(text_lines).strip()
            if not full_text:
                return None

            bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
            if bubbles:
                logger.info("📋 Found snippet '%s': %d bubbles", header_name, len(bubbles))
                return bubbles
            return None
        i += 1

    return None


def get_product_snippet(product_name: str) -> list[str] | None:
    """Get presentation snippet for a product from snippets.md.

    Returns list of bubbles (split by ---) or None if not found.
    Universal: works for ANY product that has a snippet in snippets.md.

    Format in snippets.md:
        ### Сукня Анна — преміум-презентація
        КОЛИ: ...
        Текст бабла 1
        ---
        Текст бабла 2

    Args:
        product_name: Product name to search for (e.g., "Сукня Анна")

    Returns:
        List of bubble texts or None if not found
    """
    try:
        from src.core.prompt_registry import registry

        # Optimize: Product snippets are only in snippets.products
        content = registry.get("snippets.products").content
    except Exception:
        return None

    if not content:
        return None

    # Normalize product name for matching
    pn_lower = (product_name or "").lower().strip()
    if not pn_lower:
        return None

    # КРИТИЧНО: Удаляем цвет в скобках и другие дополнения
    # "Сукня Анна (лео рожева)" -> "Сукня Анна"
    # "Костюм Лагуна (синий)" -> "Костюм Лагуна"
    import re
    # Удаляем все в скобках: (лео рожева), (синий), etc.
    pn_clean = re.sub(r'\([^)]*\)', '', pn_lower).strip()
    # Удаляем лишние пробелы
    pn_clean = ' '.join(pn_clean.split())
    
    # Extract key words (e.g., "сукня анна" -> ["сукня", "анна"])
    keywords = [w for w in pn_clean.split() if len(w) > 2]
    if not keywords:
        return None
    
    logger.debug(
        "🔍 Searching snippet for product: original='%s', cleaned='%s', keywords=%s",
        product_name,
        pn_clean,
        keywords,
    )

    # Parse snippets.md - find sections matching product
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for ### headers that contain product keywords
        if line.startswith("### "):
            header_lower = line[4:].lower()

            # Check if this header matches our product (all keywords present)
            if all(kw in header_lower for kw in keywords):
                # Found a match! Look for "презентація" or first snippet for this product
                if "презентація" in header_lower or "відповідь" in header_lower:
                    # Extract the snippet body (until next ### or EOF)
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("### "):
                        body_lines.append(lines[i])
                        i += 1

                    # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
                    text_lines = []
                    for bl in body_lines:
                        bl_stripped = bl.strip()
                        if (
                            bl_stripped.startswith("КОЛИ:")
                            or bl_stripped.startswith("НЕ КОЛИ:")
                            or bl_stripped.startswith("ПРІОРИТЕТ:")
                        ):
                            continue
                        text_lines.append(bl_stripped)

                    # Join and split by ---
                    full_text = "\n".join(text_lines).strip()
                    if not full_text:
                        return None

                    bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
                    if bubbles:
                        logger.info(
                            "📋 Found snippet for '%s': %d bubbles", product_name, len(bubbles)
                        )
                        return bubbles
                    return None
        i += 1

    return None

