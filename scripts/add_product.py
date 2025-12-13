#!/usr/bin/env python3
"""
🛍️ ПРОСТИЙ СКРИПТ ДЛЯ ДОДАВАННЯ ПРОДУКТУ
==========================================

Запуск:
    python scripts/add_product.py

Що робить:
1. Запитує основні дані (назва, ціни, кольори)
2. Автоматично додає в products_master.yaml
3. Генерує артефакти vision
4. Оновлює БД Supabase

Приклад:
    Назва: Костюм Весна
    Категорія: костюми
    Кольори (через кому): рожевий, голубий
    Ціна однакова для всіх розмірів? [y/n]: y
    Ціна: 1850
    → Готово! Продукт додано.
"""

import sys
import json
import yaml
import asyncio
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PRODUCTS_MASTER = PROJECT_ROOT / "data" / "vision" / "products_master.yaml"


def load_yaml():
    """Load products_master.yaml."""
    with open(PRODUCTS_MASTER, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(data):
    """Save products_master.yaml."""
    with open(PRODUCTS_MASTER, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def ask(prompt: str, default: str = "") -> str:
    """Ask user for input."""
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Ask yes/no question."""
    suffix = "[Y/n]" if default else "[y/N]"
    result = input(f"{prompt} {suffix}: ").strip().lower()
    if not result:
        return default
    return result in ("y", "yes", "так", "да")


def generate_product_key(name: str) -> str:
    """Generate YAML key from product name."""
    # "Костюм Весна" -> "kostum_vesna"
    import re
    # Transliterate Ukrainian
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'є': 'ye',
        'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's',
        'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh',
        'щ': 'shch', 'ь': '', 'ю': 'yu', 'я': 'ya', "'": '', ' ': '_'
    }
    result = ""
    for char in name.lower():
        result += translit.get(char, char)
    return re.sub(r'[^a-z0-9_]', '', result)


def get_standard_sizes() -> list[str]:
    """Return standard size options."""
    return [
        "80-92", "98-104", "110-116", "122-128", 
        "134-140", "146-152", "158-164"
    ]


def main():
    print("=" * 60)
    print("🛍️  ДОДАВАННЯ НОВОГО ПРОДУКТУ")
    print("=" * 60)
    print()
    
    # 1. ОСНОВНІ ДАНІ
    print("📝 КРОК 1: Основні дані")
    print("-" * 40)
    
    name = ask("Назва товару (напр. 'Костюм Весна')")
    if not name:
        print("❌ Назва обов'язкова!")
        sys.exit(1)
    
    category = ask("Категорія", "костюми")
    
    # 2. КОЛЬОРИ
    print()
    print("🎨 КРОК 2: Кольори")
    print("-" * 40)
    
    colors_input = ask("Кольори через кому (напр. 'рожевий, голубий')")
    colors = [c.strip() for c in colors_input.split(",") if c.strip()]
    
    if not colors:
        colors = ["універсальний"]
        print("   → Встановлено: універсальний")
    
    # 3. ЦІНИ
    print()
    print("💰 КРОК 3: Ціни")
    print("-" * 40)
    
    uniform_price = ask_yes_no("Ціна однакова для всіх розмірів?", default=True)
    
    sizes = get_standard_sizes()
    
    if uniform_price:
        price_str = ask("Ціна (грн)")
        try:
            price = int(price_str)
        except ValueError:
            print("❌ Невірний формат ціни!")
            sys.exit(1)
        
        prices_by_size = {size: price for size in sizes}
    else:
        print("   Введіть ціни для кожного розміру:")
        prices_by_size = {}
        for size in sizes:
            price_str = ask(f"   {size}")
            try:
                prices_by_size[size] = int(price_str)
            except ValueError:
                print(f"❌ Невірний формат для {size}!")
                sys.exit(1)
    
    # 4. ФОТО (опціонально)
    print()
    print("📷 КРОК 4: Фото URL (опціонально)")
    print("-" * 40)
    print("   Вставте URL фото для кожного кольору або натисніть Enter щоб пропустити")
    
    color_data = {}
    for color in colors:
        photo_url = ask(f"   URL для '{color}' (Enter = пропустити)")
        sku = f"{generate_product_key(name).upper()}-{color.upper()[:4]}"
        color_data[color] = {
            "photo_url": photo_url if photo_url else "",
            "sku": sku
        }
    
    # 5. ГЕНЕРАЦІЯ СТРУКТУРИ
    print()
    print("⚙️  Генерую структуру...")
    
    product_key = generate_product_key(name)
    
    product = {
        "id": int(datetime.now().timestamp()),  # Унікальний ID
        "name": name,
        "category": category,
        "price_type": "by_size",
        "prices_by_size": prices_by_size,
        "colors": color_data,
        "visual": {
            "fabric_type": "тканина",
            "key_markers": [
                f"Характерні ознаки {name}"
            ],
            "recognition_by_angle": {
                "front": "Вигляд спереду",
                "back": "Вигляд ззаду",
                "side": "Вигляд збоку",
                "detail": "Деталі"
            },
            "low_quality_markers": [
                "Ознаки на фото низької якості"
            ],
            "texture_description": "Опис текстури тканини"
        },
        "distinction": {
            "confused_with": [],
            "unique_identifier": f"Унікальна ознака {name}"
        }
    }
    
    # 6. ЗБЕРІГАННЯ
    print("💾 Зберігаю в products_master.yaml...")
    
    data = load_yaml()
    if "products" not in data:
        data["products"] = {}
    
    data["products"][product_key] = product
    save_yaml(data)
    
    print("   ✅ Збережено!")
    
    # 7. ГЕНЕРАЦІЯ АРТЕФАКТІВ
    print()
    print("🔧 Генерую артефакти vision...")
    
    try:
        from data.vision.generate import main as generate_artifacts
        generate_artifacts()
        print("   ✅ Артефакти згенеровано!")
    except Exception as e:
        print(f"   ⚠️ Помилка генерації: {e}")
        print("   Запустіть вручну: python scripts/generate_vision_artifacts.py")
    
    # 8. ОНОВЛЕННЯ БД
    print()
    if ask_yes_no("Оновити БД Supabase?", default=True):
        print("🔌 Оновлюю БД...")
        try:
            from scripts.migrate_price_by_size import main as migrate
            migrate()
            print("   ✅ БД оновлено!")
        except Exception as e:
            print(f"   ⚠️ Помилка БД: {e}")
            print("   Запустіть вручну: python scripts/migrate_price_by_size.py")
    
    # ГОТОВО
    print()
    print("=" * 60)
    print("✅ ГОТОВО!")
    print("=" * 60)
    print()
    print(f"Товар '{name}' додано успішно!")
    print()
    print("📋 Що було зроблено:")
    print(f"   • Додано в products_master.yaml ({product_key})")
    print(f"   • Кольори: {', '.join(colors)}")
    print(f"   • Ціни: {min(prices_by_size.values())}-{max(prices_by_size.values())} грн")
    print()
    print("⚡ Наступні кроки:")
    print("   1. Додайте фото URL якщо пропустили")
    print("   2. Уточніть visual.key_markers для розпізнавання")
    print("   3. Протестуйте: надішліть фото в бота")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Скасовано")
        sys.exit(0)
