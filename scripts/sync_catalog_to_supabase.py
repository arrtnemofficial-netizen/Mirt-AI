"""
Sync YAML catalog to Supabase products table.

This script reads the embedded catalog from prompts/blocks/catalog.yaml
and updates the Supabase products table with correct prices and data.
"""
import json
import yaml
from pathlib import Path

# Catalog data extracted from user's YAML
CATALOG = {
    # Сукня Анна variants
    "3443041": {"name": "Сукня Анна", "price_uniform": True, "price": 1850, "colors": ["голубий", "малина", "чорний"]},
    "3786442": {"name": "Сукня Анна (червона клітинка)", "price_uniform": True, "price": 1850, "colors": ["червоний"]},
    "3646358": {"name": "Сукня Анна (шоколад)", "price_uniform": True, "price": 1850, "colors": ["коричневий"]},
    "3663608": {"name": "Сукня Анна (лео рожева)", "price_uniform": True, "price": 1850, "colors": ["рожевий"]},
    "3646356": {"name": "Сукня Анна (сіра)", "price_uniform": True, "price": 1850, "colors": ["сірий"]},
    
    # Костюм Валері
    "9251497": {"name": "Костюм Валері", "price_uniform": True, "price": 1950, "colors": ["універсальний"]},
    
    # Костюм Ритм
    "11089055": {"name": "Костюм Ритм (рожевий)", "price_uniform": True, "price": 1975, "colors": ["рожевий"]},
    "11089244": {"name": "Костюм Ритм (шоколад)", "price_uniform": True, "price": 1975, "colors": ["коричневий"]},
    "11089288": {"name": "Костюм Ритм (бордо)", "price_uniform": True, "price": 1975, "colors": ["бордовий"]},
    
    # Костюм Каприз
    "11100944": {"name": "Костюм Каприз (рожевий)", "price_uniform": True, "price": 1885, "colors": ["рожевий"]},
    "11101056": {"name": "Костюм Каприз (бордо)", "price_uniform": True, "price": 1885, "colors": ["бордовий"]},
    "11101074": {"name": "Костюм Каприз (шоколад)", "price_uniform": True, "price": 1885, "colors": ["коричневий"]},
    
    # Костюм Лагуна - ЦІНА ЗАЛЕЖИТЬ ВІД РОЗМІРУ!
    "11698818": {
        "name": "Костюм Лагуна (рожевий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["рожевий"],
        "material": "плюш",
        "closure": "full_zip",  # ПОВНА блискавка!
    },
    "11703918": {
        "name": "Костюм Лагуна (помаранчевий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["помаранчевий"],
        "material": "плюш",
        "closure": "full_zip",
    },
    "11704797": {
        "name": "Костюм Лагуна (жовтий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["жовтий"],
        "material": "плюш",
        "closure": "full_zip",
    },
    "11762726": {
        "name": "Костюм Лагуна (сірий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["сірий"],
        "material": "плюш",
        "closure": "full_zip",
    },
    
    # Костюм Мрія - ЦІНА ЗАЛЕЖИТЬ ВІД РОЗМІРУ!
    "11705284": {
        "name": "Костюм Мрія (жовтий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["жовтий"],
        "material": "плюш",
        "closure": "half_zip",  # Half-zip!
    },
    "11903529": {
        "name": "Костюм Мрія (рожевий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["рожевий"],
        "material": "плюш",
        "closure": "half_zip",
    },
    "11919011": {
        "name": "Костюм Мрія (помаранчевий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["помаранчевий"],
        "material": "плюш",
        "closure": "half_zip",
    },
    "11922371": {
        "name": "Костюм Мрія (сірий)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1590, "98-104": 1790, "110-116": 1990, "122-128": 2190, "134-140": 2290, "146-152": 2390, "158-164": 2390},
        "colors": ["сірий"],
        "material": "плюш",
        "closure": "half_zip",
    },
    
    # Костюм Мерея
    "11995414": {
        "name": "Костюм Мерея (молочний)", 
        "price_uniform": False, 
        "price_by_size": {"80-92": 1985, "98-104": 1985, "110-116": 1985, "122-128": 1985, "134-140": 2150, "146-152": 2150, "158-164": 2150},
        "colors": ["молочний"],
    },
    
    # Тренч екошкіра
    "3482676": {"name": "Тренч екошкіра (капучіно)", "price_uniform": True, "price": 2180, "colors": ["капучіно"]},
    "3482679": {"name": "Тренч екошкіра (молочний)", "price_uniform": True, "price": 2180, "colors": ["молочний"]},
    "3482682": {"name": "Тренч екошкіра (чорний)", "price_uniform": True, "price": 2180, "colors": ["чорний"]},
    
    # Тренч тканинний
    "5888646": {"name": "Тренч (рожевий)", "price_uniform": True, "price": 2380, "colors": ["рожевий"]},
    "5888667": {"name": "Тренч (голубий)", "price_uniform": True, "price": 2380, "colors": ["голубий"]},
    "5907679": {"name": "Тренч (темно синій)", "price_uniform": True, "price": 2380, "colors": ["темно синій"]},
}


def main():
    from src.services.supabase_client import get_supabase_client
    
    client = get_supabase_client()
    if not client:
        print("❌ Supabase client not available!")
        return
    
    print("📦 Syncing catalog to Supabase...\n")
    
    # Get existing products
    existing = client.table("products").select("id, name, sku").execute()
    existing_by_sku = {p.get("sku", "").split("-")[0]: p for p in existing.data}
    
    updated = 0
    created = 0
    
    for sku, data in CATALOG.items():
        name = data["name"]
        colors = data.get("colors", [])
        
        # Calculate display price (min price for variable pricing)
        if data.get("price_uniform"):
            price = data["price"]
            price_info = f"{price} грн (всі розміри)"
        else:
            prices = data.get("price_by_size", {})
            price = min(prices.values()) if prices else 0
            max_price = max(prices.values()) if prices else 0
            price_info = f"{price}-{max_price} грн (залежить від розміру)"
        
        # Check if exists
        existing_product = existing_by_sku.get(sku)
        
        update_data = {
            "name": name,
            "price": price,
            "colors": colors,
            "description": f"{name}. Ціна: {price_info}",
        }
        
        # Add price_by_size as JSON if variable pricing
        if not data.get("price_uniform"):
            update_data["sizes"] = list(data.get("price_by_size", {}).keys())
        
        if existing_product:
            # Update existing
            client.table("products").update(update_data).eq("id", existing_product["id"]).execute()
            print(f"✅ Updated: {name} | {price_info}")
            updated += 1
        else:
            # Create new
            update_data["sku"] = f"{sku}-{colors[0].upper()[:4]}" if colors else sku
            client.table("products").insert(update_data).execute()
            print(f"🆕 Created: {name} | {price_info}")
            created += 1
    
    print(f"\n✅ Done! Updated: {updated}, Created: {created}")


if __name__ == "__main__":
    main()
