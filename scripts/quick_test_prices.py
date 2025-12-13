#!/usr/bin/env python
"""Quick test for price_by_size."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.catalog_service import CatalogService

async def test():
    cs = CatalogService()
    
    print("=== ТЕСТ PRICE_BY_SIZE ===\n")
    
    # Тест Лагуна
    result = await cs.search_products("Лагуна", limit=1)
    if result:
        p = result[0]
        print(f"Товар: {p['name']}")
        print(f"price_by_size: {p.get('price_by_size')}")
        
        price_128 = cs.get_price_for_size(p, "122-128")
        price_80 = cs.get_price_for_size(p, "80-92")
        
        print(f"\nЦіна 122-128: {price_128} (очікується 2190)")
        print(f"Ціна 80-92: {price_80} (очікується 1590)")
        print(f"Діапазон: {cs.format_price_display(p)}")
        
        if price_128 == 2190 and price_80 == 1590:
            print("\n✅ ВСЕ ПРАЦЮЄ ПРАВИЛЬНО!")
            return 0
        else:
            print("\n❌ ЦІНИ НЕПРАВИЛЬНІ!")
            return 1
    else:
        print("❌ Лагуна не знайдена!")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
