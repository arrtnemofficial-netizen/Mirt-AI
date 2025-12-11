#!/usr/bin/env python
"""
Міграція: Додати price_by_size для товарів з варіативними цінами.

Читає ціни з products_master.yaml і оновлює products в Supabase.

Usage:
    python scripts/migrate_price_by_size.py
"""

import asyncio
import json
import sys
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from src.conf.config import settings


def load_prices_from_yaml() -> dict[str, dict]:
    """Завантажує ціни з products_master.yaml."""
    yaml_path = Path(__file__).parent.parent / "data" / "vision" / "products_master.yaml"
    
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    products = data.get("products", {})
    
    # Збираємо товари з price_type: "by_size"
    prices_map = {}
    for key, product in products.items():
        if product.get("price_type") == "by_size":
            name = product["name"]
            prices = product.get("prices_by_size", {})
            if prices:
                prices_map[name] = prices
                print(f"  📦 {name}: {len(prices)} розмірів")
    
    return prices_map


def main():
    print("=" * 60)
    print("МІГРАЦІЯ: price_by_size")
    print("=" * 60)
    
    # 1. Завантажуємо ціни з YAML
    print("\n📂 Читаю products_master.yaml...")
    prices_map = load_prices_from_yaml()
    print(f"\n   Знайдено {len(prices_map)} товарів з варіативними цінами")
    
    if not prices_map:
        print("❌ Немає товарів для оновлення!")
        sys.exit(1)
    
    # 2. Підключаємось до Supabase
    print("\n🔌 Підключаюсь до Supabase...")
    try:
        client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_API_KEY.get_secret_value()
        )
        print("   ✅ Підключено!")
    except Exception as e:
        print(f"❌ Помилка підключення: {e}")
        sys.exit(1)
    
    # 2.5 Перевіряємо чи існує колонка price_by_size
    print("\n🔧 Перевіряю схему...")
    try:
        # Спробуємо вибрати колонку - якщо не існує, отримаємо помилку
        test = client.table("products").select("price_by_size").limit(1).execute()
        print("   ✅ Колонка price_by_size існує")
    except Exception as e:
        if "does not exist" in str(e) or "PGRST204" in str(e):
            print("   ⚠️ Колонка price_by_size НЕ існує!")
            print("\n" + "=" * 60)
            print("❌ ПОТРІБНО СПОЧАТКУ СТВОРИТИ КОЛОНКУ!")
            print("=" * 60)
            print("\nВиконайте в Supabase SQL Editor:")
            print("-" * 60)
            print("""
ALTER TABLE products 
ADD COLUMN IF NOT EXISTS price_by_size JSONB DEFAULT NULL;

COMMENT ON COLUMN products.price_by_size IS 
  'Ціни по розмірах. Формат: {"80-92": 1590, "98-104": 1790, ...}';
""")
            print("-" * 60)
            print("\nПісля цього запустіть скрипт ще раз!")
            sys.exit(1)
        else:
            raise e
    
    # 3. Оновлюємо кожен товар
    print("\n📝 Оновлюю товари...")
    updated = 0
    errors = []
    
    for product_name, prices in prices_map.items():
        try:
            # Шукаємо всі товари з цією базовою назвою
            # Наприклад "Костюм Лагуна" -> "Костюм Лагуна (рожевий)", "Костюм Лагуна (жовтий)" тощо
            result = client.table("products").select("id, name").ilike("name", f"{product_name}%").execute()
            
            if not result.data:
                print(f"   ⚠️ {product_name}: не знайдено в БД")
                continue
            
            # Оновлюємо кожен знайдений товар
            for product in result.data:
                update_result = client.table("products").update({
                    "price_by_size": prices
                }).eq("id", product["id"]).execute()
                
                if update_result.data:
                    print(f"   ✅ {product['name']}")
                    updated += 1
                else:
                    errors.append(f"{product['name']}: update failed")
                    
        except Exception as e:
            errors.append(f"{product_name}: {e}")
            print(f"   ❌ {product_name}: {e}")
    
    # 4. Результат
    print("\n" + "=" * 60)
    print(f"РЕЗУЛЬТАТ: Оновлено {updated} товарів")
    
    if errors:
        print(f"\n⚠️ Помилки ({len(errors)}):")
        for err in errors:
            print(f"   • {err}")
    
    # 5. Перевірка
    print("\n🔍 Перевірка...")
    result = client.table("products").select("name, price_by_size").not_.is_("price_by_size", "null").execute()
    
    if result.data:
        print(f"   Товарів з price_by_size: {len(result.data)}")
        for p in result.data[:3]:
            print(f"   • {p['name']}: {p['price_by_size']}")
        if len(result.data) > 3:
            print(f"   ... і ще {len(result.data) - 3}")
    else:
        print("   ❌ Жодного товару з price_by_size!")
        sys.exit(1)
    
    print("\n✅ МІГРАЦІЯ ЗАВЕРШЕНА!")


if __name__ == "__main__":
    main()
