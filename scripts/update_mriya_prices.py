"""
Update Костюм Мрія prices in Supabase.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

def main():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_API_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not url or not key:
        print('ERROR: SUPABASE_URL or SUPABASE_API_KEY not set')
        print(f"  SUPABASE_URL: {'set' if url else 'NOT SET'}")
        print(f"  SUPABASE_API_KEY: {'set' if key else 'NOT SET'}")
        return
    
    print(f"Connecting to Supabase: {url[:50]}...")

    client = create_client(url, key)

    # Нові ціни для Мрія (такі ж як Лагуна)
    new_prices = {
        "80-92": 1590,
        "98-104": 1790,
        "110-116": 1990,
        "122-128": 2190,
        "134-140": 2290,
        "146-152": 2390,
        "158-164": 2390
    }

    # Спершу дізнаємось структуру таблиці
    test_result = client.table('products').select('*').limit(1).execute()
    if test_result.data:
        print(f"Колонки в таблиці: {list(test_result.data[0].keys())}")
    
    min_price = 1590  # Мінімальна ціна для розміру 80-92
    
    # Оновити Мрія і Лагуна
    for pattern in ['%Мрія%', '%Лагуна%']:
        result = client.table('products').select('*').ilike('name', pattern).execute()
        product_type = "Мрія" if "Мрія" in pattern else "Лагуна"
        
        print(f"\nЗнайдено {len(result.data)} товарів {product_type}:")
        for p in result.data:
            prod_id = p['id']
            prod_name = p['name']
            old_price = p.get('price')
            print(f"  - {prod_name} (id={prod_id}), стара ціна: {old_price}")
        
        for p in result.data:
            prod_id = p['id']
            prod_name = p['name']
            client.table('products').update({'price': min_price}).eq('id', prod_id).execute()
            print(f"  ✅ Оновлено: {prod_name} → {min_price} грн")

    print(f"\n✅ Базові ціни Мрія і Лагуна оновлено на {min_price} грн!")
    print("   (Ціни за розмір беруться з products_master.yaml)")


if __name__ == "__main__":
    main()
