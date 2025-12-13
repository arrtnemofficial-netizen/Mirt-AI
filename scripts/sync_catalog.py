"""
Full Catalog Sync Script.
=========================
Parses the YAML catalog and inserts ALL products into Supabase.
Each color variant becomes a SEPARATE row with its own SKU, photo, and description.
"""

import asyncio
import logging
from pathlib import Path
import yaml

from src.services.supabase_client import get_supabase_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).parent.parent / "data" / "system_prompt_full.yaml"


def parse_catalog() -> list[dict]:
    """Parse the YAML catalog and extract all products with color variants."""
    products = []
    
    with open(CATALOG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    catalog = data.get("catalog", {})
    
    # Iterate through all categories (category_001, category_002, etc.)
    for cat_key, category in catalog.items():
        if not cat_key.startswith("category_"):
            continue
        
        category_name = category.get("name", "")
        category_products = category.get("products", {})
        
        for product_id, product in category_products.items():
            base_name = product.get("name", "")
            variant_name = product.get("variant_name") or product.get("color_variant", "")
            subcategory = product.get("subcategory", "")
            sizes = product.get("sizes", [])
            material = product.get("material", "")
            
            # Price handling
            price_uniform = product.get("price_uniform", False)
            price_all_sizes = product.get("price_all_sizes")
            price_by_size = product.get("price_by_size", {})
            
            colors = product.get("colors", {})
            
            # Each color becomes a separate product row
            for color_name, color_data in colors.items():
                photo_url = color_data.get("photo_url", "")
                description = color_data.get("description", "")
                sku = color_data.get("sku", f"{product_id}-{color_name.upper()[:3]}")
                
                # Build full product name
                full_name = base_name
                if variant_name:
                    full_name = f"{base_name} ({variant_name})"
                
                # Determine price
                if price_uniform and price_all_sizes:
                    price = price_all_sizes
                elif price_by_size:
                    # Use average or first available price
                    prices = list(price_by_size.values())
                    price = sum(prices) / len(prices) if prices else 0
                else:
                    price = 0
                
                # Build full description with material
                full_description = description
                if material:
                    full_description = f"{description} Матеріал: {material}."
                
                products.append({
                    "name": full_name,
                    "description": full_description,
                    "category": category_name.lower() if category_name else product.get("category", ""),
                    "subcategory": subcategory,
                    "price": round(price, 2),
                    "sizes": sizes,
                    "colors": [color_name],  # Single color per row
                    "photo_url": photo_url,
                    "sku": sku,
                })
    
    return products


async def sync_catalog():
    """Sync catalog to Supabase."""
    client = get_supabase_client()
    if not client:
        print("❌ Could not connect to Supabase. Check .env")
        return
    
    print("🚀 Starting FULL catalog sync...")
    
    # Parse catalog from YAML
    products = parse_catalog()
    print(f"📦 Found {len(products)} product variants to sync")
    
    # Clear existing products (optional - fresh sync)
    try:
        client.table("products").delete().neq("id", 0).execute()
        print("🗑️ Cleared existing products")
    except Exception as e:
        print(f"⚠️ Could not clear products: {e}")
    
    inserted = 0
    errors = 0
    
    for p in products:
        try:
            result = client.table("products").insert(p).execute()
            if result.data:
                print(f"✅ {p['name']} ({p['colors'][0]}): {p['price']} грн")
                inserted += 1
            else:
                print(f"⚠️ No data returned for {p['name']}")
        except Exception as e:
            print(f"❌ Error inserting {p['name']}: {e}")
            errors += 1
    
    print(f"\n🏁 Sync complete!")
    print(f"   ✅ Inserted: {inserted}")
    print(f"   ❌ Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(sync_catalog())
