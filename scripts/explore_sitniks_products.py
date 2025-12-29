import asyncio
import os
import json
import httpx
from pydantic import SecretStr

# Mock settings class to run standalone
class Settings:
    def __init__(self):
        self.SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
        self.SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")

settings = Settings()

async def explore_products():
    print(f"🔭 Exploring Sitniks CRM at {settings.SNITKIX_API_URL}...")
    
    if not settings.SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing in env variables.")
        return

    headers = {
        "Authorization": f"Bearer {settings.SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Potential endpoints to try
    endpoints = [
        "/open-api/products", 
        "/open-api/catalog", 
        "/open-api/items",
        "/open-api/goods"
    ]
    
    async with httpx.AsyncClient(timeout=10) as client:
        for ep in endpoints:
            url = f"{settings.SNITKIX_API_URL}{ep}"
            print(f"Trying GET {url}...")
            try:
                response = await client.get(url, headers=headers, params={"limit": 5})
                print(f"Status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    print("✅ SUCCESS! Found data.")
                    
                    # Save sample to file
                    filename = "sitniks_products_sample.json"
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"Saved sample response to {filename}")
                    
                    # Analyze structure
                    items = data.get("data", [])
                    print(f"Found {len(items)} items in sample.")
                    if items:
                        first = items[0]
                        print("Sample Item Keys:", first.keys())
                    return
                else:
                    print(f"Failed: {response.text[:100]}")
                    
            except Exception as e:
                print(f"Error: {e}")
                
    print("❌ Could not find a working products endpoint.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(explore_products())
