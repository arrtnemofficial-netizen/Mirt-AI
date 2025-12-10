"""Debug catalog search - find why vision fails."""
import asyncio
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from src.services.catalog_service import CatalogService


async def main():
    cs = CatalogService()
    
    print("=" * 60)
    print("1. Testing get_products_for_vision()...")
    print("=" * 60)
    
    products = await cs.get_products_for_vision()
    print(f"Total products: {len(products)}")
    
    if products:
        print("\nFirst 10 products:")
        for p in products[:10]:
            print(f"  - {p.get('name')} | price={p.get('price')}")
    else:
        print("❌ NO PRODUCTS RETURNED!")
    
    print("\n" + "=" * 60)
    print("2. Testing search_products('Лагуна')...")
    print("=" * 60)
    
    laguna = await cs.search_products("Лагуна", limit=5)
    print(f"Found: {len(laguna)} products")
    for p in laguna:
        print(f"  - {p.get('name')} | price={p.get('price')}")
    
    print("\n" + "=" * 60)
    print("3. Testing search_products('помаранчевий')...")
    print("=" * 60)
    
    orange = await cs.search_products("помаранчевий", limit=5)
    print(f"Found: {len(orange)} products")
    for p in orange:
        print(f"  - {p.get('name')} | price={p.get('price')}")
    
    print("\n" + "=" * 60)
    print("4. Check if client is connected...")
    print("=" * 60)
    print(f"Supabase client: {cs.client is not None}")


if __name__ == "__main__":
    asyncio.run(main())
