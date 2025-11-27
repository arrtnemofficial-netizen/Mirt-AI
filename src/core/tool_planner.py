"""
Tool Planner - вибір інструментів у коді.
=========================================
Винесення логіки вибору tool з промпта в код.
LLM отримує вже tool_result або інструкцію.

Логіка:
- Якщо є photo_url (наш домен) → GET_BY_PHOTO_URL
- Якщо є явний product_id → GET_BY_ID
- Якщо є текстовий опис → SEARCH_BY_QUERY
- Інакше → без інструментів

Використання:
    from src.core.tool_planner import ToolPlanner, ToolPlan
    
    plan = ToolPlanner.create_plan(
        text="шукаю сукню",
        image_url=None,
        current_state=State.STATE_1_DISCOVERY,
        intent=Intent.DISCOVERY_OR_QUESTION
    )
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.state_machine import State, Intent, ToolName

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL PLAN
# =============================================================================

@dataclass
class ToolCall:
    """Single tool call specification."""
    tool: ToolName
    params: Dict[str, Any]
    reason: str  # Why this tool was selected


@dataclass
class ToolPlan:
    """Plan of tool calls to execute before LLM."""
    calls: List[ToolCall] = field(default_factory=list)
    skip_llm_tools: bool = False  # If True, LLM should not call tools itself
    instruction: str = ""  # Instruction for LLM about tool results
    
    @property
    def has_tools(self) -> bool:
        return len(self.calls) > 0
    
    def add_call(self, tool: ToolName, params: Dict[str, Any], reason: str) -> None:
        self.calls.append(ToolCall(tool=tool, params=params, reason=reason))


# =============================================================================
# TOOL PLANNER
# =============================================================================

class ToolPlanner:
    """
    Determines which tools to call based on input.
    Runs BEFORE LLM to pre-fetch data.
    """
    
    # Our allowed photo domains
    OUR_PHOTO_DOMAINS = (
        "cdn.sitniks.com",
        "sitniks.com",
        "mirt.store",
        "cdn.mirt.store",
    )
    
    # Regex for extracting product ID from text
    PRODUCT_ID_PATTERN = re.compile(r"\b(?:id|product[_\-]?id|артикул)[:\s]*(\d+)\b", re.IGNORECASE)
    
    # Keywords that suggest product search
    SEARCH_KEYWORDS = {
        "uk": ["сукн", "костюм", "тренч", "плаття", "одяг", "розмір", "колір", "модель"],
        "en": ["dress", "suit", "trench", "clothing", "size", "color", "model"],
    }
    
    @classmethod
    def create_plan(
        cls,
        text: str,
        image_url: Optional[str],
        current_state: State,
        intent: Optional[Intent] = None,
        product_id: Optional[int] = None,
    ) -> ToolPlan:
        """
        Create tool execution plan based on input.
        
        Priority:
        1. Explicit product_id → GET_BY_ID
        2. Our photo_url → GET_BY_PHOTO_URL
        3. External photo → describe + SEARCH_BY_QUERY
        4. Text with keywords → SEARCH_BY_QUERY
        5. No tools needed
        """
        plan = ToolPlan()
        
        # 1. Check for explicit product ID
        if product_id:
            plan.add_call(
                ToolName.GET_BY_ID,
                {"product_id": str(product_id)},
                "Explicit product_id provided"
            )
            plan.skip_llm_tools = True
            plan.instruction = "Дані продукту вже отримані через GET_BY_ID."
            return plan
        
        # 1b. Try to extract product_id from text
        extracted_id = cls._extract_product_id(text)
        if extracted_id:
            plan.add_call(
                ToolName.GET_BY_ID,
                {"product_id": str(extracted_id)},
                f"Extracted product_id {extracted_id} from text"
            )
            plan.skip_llm_tools = True
            plan.instruction = f"Знайдено ID продукту {extracted_id} в тексті. Дані отримані."
            return plan
        
        # 2. Check for photo URL from our domain
        if image_url and cls._is_our_photo(image_url):
            plan.add_call(
                ToolName.GET_BY_PHOTO_URL,
                {"photo_url": image_url},
                "Photo URL from our domain"
            )
            plan.skip_llm_tools = True
            plan.instruction = "Фото з нашого каталогу. Пошук за URL."
            return plan
        
        # 3. External photo - will need Vision + search
        if image_url and not cls._is_our_photo(image_url):
            # Don't call tool here - LLM needs to describe the image first
            plan.skip_llm_tools = False
            plan.instruction = (
                "Фото від клієнта (не з каталогу). "
                "Опиши фото і виклич T_SUPABASE_SEARCH_BY_QUERY з описом."
            )
            return plan
        
        # 4. Intent-based tool selection
        if intent == Intent.PHOTO_IDENT and not image_url:
            # Photo intent but no image - ask for photo
            plan.instruction = "Intent PHOTO_IDENT але фото відсутнє. Попроси надіслати фото."
            return plan
        
        # 5. Text-based search
        if text and cls._needs_product_search(text, current_state, intent):
            plan.add_call(
                ToolName.SEARCH_BY_QUERY,
                {"user_query": text},
                "Text contains product search keywords or discovery intent"
            )
            plan.skip_llm_tools = True
            plan.instruction = "Семантичний пошук за текстом запиту."
            return plan
        
        # 6. No tools needed
        plan.instruction = "Інструменти не потрібні для цього запиту."
        return plan
    
    @classmethod
    def _is_our_photo(cls, url: str) -> bool:
        """Check if URL is from our allowed domains."""
        if not url:
            return False
        return any(domain in url.lower() for domain in cls.OUR_PHOTO_DOMAINS)
    
    @classmethod
    def _extract_product_id(cls, text: str) -> Optional[int]:
        """Try to extract product ID from text."""
        if not text:
            return None
        match = cls.PRODUCT_ID_PATTERN.search(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None
    
    @classmethod
    def _needs_product_search(cls, text: str, state: State, intent: Optional[Intent]) -> bool:
        """Determine if text needs product search."""
        if not text:
            return False
        
        text_lower = text.lower()
        
        # Check intent
        if intent in (Intent.DISCOVERY_OR_QUESTION, Intent.SIZE_HELP, Intent.COLOR_HELP):
            return True
        
        # Check state
        if state in (State.STATE_1_DISCOVERY, State.STATE_2_VISION, State.STATE_3_SIZE_COLOR):
            # Check for product-related keywords
            for lang_keywords in cls.SEARCH_KEYWORDS.values():
                if any(kw in text_lower for kw in lang_keywords):
                    return True
        
        return False


# =============================================================================
# TOOL EXECUTOR
# =============================================================================

async def execute_tool_plan(plan: ToolPlan) -> Dict[str, Any]:
    """
    Execute tool plan and return results.
    
    Returns dict with:
    - tool_results: List of results from tool calls
    - instruction: Updated instruction for LLM
    - success: Whether all tools succeeded
    """
    from src.services.supabase_tools import search_by_query, get_by_id, get_by_photo_url
    
    results = {
        "tool_results": [],
        "instruction": plan.instruction,
        "success": True,
        "errors": [],
    }
    
    for call in plan.calls:
        try:
            if call.tool == ToolName.SEARCH_BY_QUERY:
                result = await search_by_query(call.params.get("user_query", ""))
            elif call.tool == ToolName.GET_BY_ID:
                result = await get_by_id(call.params.get("product_id", ""))
            elif call.tool == ToolName.GET_BY_PHOTO_URL:
                result = await get_by_photo_url(call.params.get("photo_url", ""))
            else:
                result = []
            
            results["tool_results"].append({
                "tool": call.tool.value,
                "params": call.params,
                "result": result,
                "reason": call.reason,
            })
            
            logger.info("Tool %s executed: %d results", call.tool.value, len(result) if result else 0)
            
        except Exception as e:
            logger.error("Tool %s failed: %s", call.tool.value, e)
            results["errors"].append(str(e))
            results["success"] = False
    
    # Update instruction based on results
    if results["tool_results"]:
        total_products = sum(
            len(r["result"]) if r["result"] else 0 
            for r in results["tool_results"]
        )
        if total_products > 0:
            results["instruction"] = f"Знайдено {total_products} товар(ів). Дані доступні в tool_result."
        else:
            results["instruction"] = "Товарів за запитом не знайдено. Попроси уточнити."
    
    return results
