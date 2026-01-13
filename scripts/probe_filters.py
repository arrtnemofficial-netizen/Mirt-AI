import asyncio
import os
import httpx

SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")

async def probe_filters():
    if not SNITKIX_API_KEY:
        print("❌ Key missing")
        return

    print(f"🧠 Brainstorming Filters on {SNITKIX_API_URL}...")
    headers = {"Authorization": f"Bearer {SNITKIX_API_KEY}"}
    
    # List of potential guesses
    potential_params = [
        {}, # Baseline (All)
        {"isActive": "true"},
        {"isActive": "1"},
        {"status": "active"},
        {"filter[isActive]": "true"},
        {"filter[status]": "active"},
        {"visible": "true"},
        {"inStock": "true"}
    ]
    
    async with httpx.AsyncClient(timeout=10) as client:
        url = f"{SNITKIX_API_URL}/open-api/products"
        
        # 1. Get Baseline Count (first page only)
        # We can't get total easily, but duplicates in the list might give a hint?
        # Actually, let's just check if the DATA changes.
        
        baseline_ids = []
        print("1️⃣ Establishing Baseline (No Filter)...")
        resp = await client.get(url, headers=headers, params={"limit": 10})
        if resp.status_code == 200:
            baseline_items = resp.json().get("data", [])
            baseline_ids = [str(x['id']) for x in baseline_items]
            print(f"   Baseline IDs: {baseline_ids}")
        else:
            print("   Baseline failed.")
            return

        # 2. Test Filters
        print("\n2️⃣ Testing Candidates...")
        for p in potential_params[1:]:
            print(f"   Trying params: {p} ...", end=" ")
            try:
                # Add limit=10
                test_p = p.copy()
                test_p["limit"] = 10
                
                resp = await client.get(url, headers=headers, params=test_p)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", [])
                    ids = [str(x['id']) for x in items]
                    
                    if not items:
                        print("❌ Empty result (Filter too aggressive?)")
                    elif ids == baseline_ids:
                        print("⚠️ Same as baseline (Filter ignored)")
                    else:
                        print(f"✅ DIFFERENT RESULT! This might be it. IDs: {ids}")
                        # If different, this filter DID something.
                else:
                    print(f"❌ Error {resp.status_code}")
            except Exception as e:
                print(f"❌ Exception {e}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(probe_filters())
