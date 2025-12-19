#!/usr/bin/env python
"""
Тест: Перевірка price_by_size після міграції.

Запустити ПІСЛЯ виконання 003_add_price_by_size.sql в Supabase.

Usage:
    python scripts/test_price_by_size.py
"""

import asyncio
import sys

from src.services.catalog_service import CatalogService


async def test_price_by_size():
    """Тестує що price_by_size працює правильно."""
    cs = CatalogService()

    print("=" * 60)
    print("ТЕСТ: price_by_size після міграції")
    print("=" * 60)

    errors = []

    # ТЕСТ 1: Костюм Лагуна - ціна для 122-128 має бути 2190
    print("\n📦 Тест 1: Костюм Лагуна (рожевий)")
    result = await cs.search_products("Лагуна рожевий", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        price_80 = cs.get_price_for_size(product, "80-92")
        price_default = cs.get_price_for_size(product)

        print(f"   price_by_size: {product.get('price_by_size')}")
        print(f"   Ціна для 122-128: {price_128} (очікується 2190)")
        print(f"   Ціна для 80-92: {price_80} (очікується 1590)")
        print(f"   Ціна без розміру: {price_default} (очікується 1590)")

        if price_128 != 2190:
            errors.append(f"Лагуна 122-128: очікувалось 2190, отримано {price_128}")
        if price_80 != 1590:
            errors.append(f"Лагуна 80-92: очікувалось 1590, отримано {price_80}")
    else:
        errors.append("Костюм Лагуна не знайдено!")

    # ТЕСТ 2: Костюм Мрія - такі ж ціни як Лагуна
    print("\n📦 Тест 2: Костюм Мрія (жовтий)")
    result = await cs.search_products("Мрія жовтий", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")

        print(f"   price_by_size: {product.get('price_by_size')}")
        print(f"   Ціна для 122-128: {price_128} (очікується 2190)")

        if price_128 != 2190:
            errors.append(f"Мрія 122-128: очікувалось 2190, отримано {price_128}")
    else:
        errors.append("Костюм Мрія не знайдено!")

    # ТЕСТ 3: Костюм Мерея - різні ціни
    print("\n📦 Тест 3: Костюм Мерея")
    result = await cs.search_products("Мерея", limit=1)
    if result:
        product = result[0]
        price_128 = cs.get_price_for_size(product, "122-128")
        price_140 = cs.get_price_for_size(product, "134-140")

        print(f"   price_by_size: {product.get('price_by_size')}")
        print(f"   Ціна для 122-128: {price_128} (очікується 1985)")
        print(f"   Ціна для 134-140: {price_140} (очікується 2150)")

        if price_128 != 1985:
            errors.append(f"Мерея 122-128: очікувалось 1985, отримано {price_128}")
        if price_140 != 2150:
            errors.append(f"Мерея 134-140: очікувалось 2150, отримано {price_140}")
    else:
        errors.append("Костюм Мерея не знайдено!")

    # ТЕСТ 4: Товар без price_by_size - fallback на price
    print("\n📦 Тест 4: Сукня Анна (без price_by_size)")
    result = await cs.search_products("Сукня Анна", limit=1)
    if result:
        product = result[0]
        price = cs.get_price_for_size(product, "122")

        print(f"   price_by_size: {product.get('price_by_size')}")
        print(f"   price: {product.get('price')}")
        print(f"   get_price_for_size: {price}")

        if price != product.get("price"):
            errors.append("Анна fallback не працює!")
    else:
        print("   (Сукня Анна не знайдена - це ОК якщо її немає в БД)")

    # ТЕСТ 5: format_price_display для варіативних цін
    print("\n📦 Тест 5: format_price_display")
    result = await cs.search_products("Лагуна", limit=1)
    if result:
        product = result[0]
        display = cs.format_price_display(product)

        print(f"   format_price_display: '{display}'")

        if "1590" in display and "2390" in display:
            print("   ✅ Показує діапазон цін!")
        else:
            errors.append(f"format_price_display не показує діапазон: {display}")

    # РЕЗУЛЬТАТ
    print("\n" + "=" * 60)
    if errors:
        print("❌ ТЕСТ НЕ ПРОЙДЕНО!")
        for err in errors:
            print(f"   • {err}")
        print("\n⚠️ Перевірте що міграція 003_add_price_by_size.sql виконана!")
        sys.exit(1)
    else:
        print("✅ ВСІ ТЕСТИ ПРОЙДЕНО!")
        print("\nСистема готова до продакшну.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(test_price_by_size())
