"""
Verification Script for PROJECT 100% QUALITY PLAN.
==================================================
Tests:
1. Phone Validation (Hard Regex + Normalization)
2. Vision Context Service (State Assembly)
3. Price Fallback Logic (SSOT)
"""
import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VERIFY")

def test_phone_validation():
    logger.info("TEST 1: Phone Validation")
    from src.services.domain.payment.payment_validation import validate_phone_number
    
    cases = [
        ("0671234567", "+380671234567"),
        ("380671234567", "+380671234567"),
        ("+380671234567", "+380671234567"),
        ("067-123-45-67", "+380671234567"),
        ("(067) 123 45 67", "+380671234567"),
        ("123", None),
        ("0000000000", "+380000000000"), # Technically valid by length/prefix logic but semantic garbage
        ("", None),
        ("invalid", None)
    ]
    
    passed = 0
    for inp, expected in cases:
        result = validate_phone_number(inp)
        if result == expected:
            passed += 1
        else:
            logger.error(f"Failed: {inp} -> {result} (Expected: {expected})")
            
    logger.info(f"Phone Validation: {passed}/{len(cases)} passed.")

async def test_vision_context():
    logger.info("\nTEST 2: Vision Context Service")
    from src.services.domain.vision.vision_context import VisionContextService
    
    # Mock Catalog
    mock_catalog = MagicMock()
    mock_catalog.get_products_for_vision = AsyncMock(return_value=[
        {
            "name": "Test Product",
            "sku": "TP-001",
            "price_by_size": {"S": 100, "M": 200},
            "recognition_tips": ["Look for X"],
            "key_features": {"fabric": "Cotton"}
        }
    ])
    
    service = VisionContextService(catalog=mock_catalog)
    
    context = await service.get_full_context()
    
    print("--- CONTEXT PREVIEW ---")
    print(context[:300] + "...")
    print("--- END PREVIEW ---")
    
    if "Test Product" in context and "Cotton" in context:
        logger.info("Vision Context: SUCCESS (Found dynamic data)")
    else:
        logger.error("Vision Context: FAILED (Data missing)")

async def test_price_fallback():
    logger.info("\nTEST 3: Price Fallback Logic (SSOT)")
    from src.agents.langgraph.nodes.utils import _get_fallback_prices_from_registry
    
    # This calls registry. Should be loaded.
    prices = _get_fallback_prices_from_registry()
    logger.info(f"Fallback Prices Loaded: {prices}")
    
    if prices and isinstance(prices, dict) and len(prices) > 0:
        logger.info("Price Fallback: SUCCESS (Registry loaded)")
    else:
        logger.error("Price Fallback: FAILED (Empty or Invalid)")

async def test_caching_performance():
    logger.info("\nTEST 4: Caching Performance (VisionContextService)")
    from src.services.domain.vision.vision_context import VisionContextService
    import time
    
    service = VisionContextService()
    
    # 1. Warm up (First call)
    start_time = time.perf_counter()
    await service.get_full_context()
    first_latency = (time.perf_counter() - start_time) * 1000
    logger.info(f"First call (Cold): {first_latency:.2f}ms")
    
    # 2. Cached call
    start_time = time.perf_counter()
    await service.get_full_context()
    cached_latency = (time.perf_counter() - start_time) * 1000
    logger.info(f"Second call (Cached): {cached_latency:.2f}ms")
    
    # 3. Invalidation
    service.invalidate_cache()
    start_time = time.perf_counter()
    await service.get_full_context()
    after_inv_latency = (time.perf_counter() - start_time) * 1000
    logger.info(f"After Invalidation: {after_inv_latency:.2f}ms")
    
    if cached_latency < first_latency and after_inv_latency > cached_latency:
        logger.info("Caching Performance: SUCCESS (Latency reduced)")
    else:
        logger.error("Caching Performance: FAILED (No improvement or invalidation failed)")

async def main():
    test_phone_validation()
    await test_vision_context()
    await test_price_fallback()
    await test_caching_performance()

if __name__ == "__main__":
    asyncio.run(main())
