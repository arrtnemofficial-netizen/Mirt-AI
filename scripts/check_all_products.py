#!/usr/bin/env python
"""Check all products in DB for sizes."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.catalog_service import CatalogService

async def check():
    cs = CatalogService()
    
    products = ['Анна', 'Валері', 'Ритм', 'Каприз', 'Тренч екошкіра', 'Тренч рожевий']
    
    for name in products:
        result = await cs.search_products(name, limit=1)
        if result:
            p = result[0]
            sizes = p.get('sizes', [])
            price = p.get('price')
            pbs = p.get('price_by_size')
            print(f"{p['name']}:")
            print(f"  price: {price}")
            print(f"  sizes: {sizes}")
            print(f"  price_by_size: {pbs}")
            print()

if __name__ == "__main__":
    asyncio.run(check())
