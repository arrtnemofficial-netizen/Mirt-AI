import asyncio
import os
import httpx

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")

async def check_count():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🕵️‍♂️ Checking Sitniks Product Count...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        # Method 1: Check Metadata in first page
        url = f"{SNITKIX_API_URL}/open-api/products"
        print(f"1. Checking metadata at {url}...")
        resp = await client.get(url, headers=headers, params={"limit": 1})
        
        if resp.status_code == 200:
            data = resp.json()
            meta = data.get("meta", {})
            print(f"   Response Meta: {meta}")
            if "total" in meta:
                print(f"   ✅ FOUND TOTAL IN META: {meta['total']}")
                return
            
            # Check Headers
            print(f"   Response Headers keys: {list(resp.headers.keys())}")
            if "x-total-count" in resp.headers:
                 print(f"   ✅ FOUND TOTAL IN HEADERS: {resp.headers['x-total-count']}")
                 return
                 
            # Method 2: Binary Search (if no total provided)
            print("   ⚠️ No total found in meta or headers. Attempting 'Binary Search' probe...")
            await probe_offsets(client, url, headers)
            
        else:
             print(f"   ❌ Error: {resp.status_code}")

async def probe_offsets(client, url, headers):
    # Exponential probe to find upper bound
    low = 0
    high = 100000
    last_found = 0
    
    # Check 10,000 to see if we have massive amount
    print(f"   Probing offset {10000}...")
    resp = await client.get(url, headers=headers, params={"limit": 1, "offset": 10000})
    if len(resp.json().get("data", [])) > 0:
        print("   -> More than 10,000 items.")
        low = 10000
    else:
        print("   -> Less than 10,000 items.")
        high = 10000
        
    # Check 50,000 if > 10k
    if low == 10000:
         print(f"   Probing offset {50000}...")
         resp = await client.get(url, headers=headers, params={"limit": 1, "offset": 50000})
         if len(resp.json().get("data", [])) > 0:
             print("   -> More than 50,000 items.")
             low = 50000
         else:
             high = 50000
             
    # Refined search would go here, but roughly:
    # We know we have at least 5000 from previous run.
    # Just giving a range is better than nothing.
    
    print(f"   📉 Estimated Range: {low} - {high} items.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_count())
