import asyncio
import os
import json
import httpx
from collections import defaultdict

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
MAX_PAGES_TO_SCAN = 100 # Scan up to 5000 items to find categories

async def infer_tree():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🌲 Inferring Category Tree from Products (limit {MAX_PAGES_TO_SCAN} pages)...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Store unique categories: ID -> {data}
    categories = {}
    
    async with httpx.AsyncClient(timeout=30) as client:
        page = 1
        limit = 50
        offset = 0
        
        while page <= MAX_PAGES_TO_SCAN:
            print(f"   Scanning page {page}...", end="\r")
            try:
                url = f"{SNITKIX_API_URL}/open-api/products"
                resp = await client.get(url, headers=headers, params={"limit": limit, "offset": offset})
                
                if resp.status_code != 200:
                    break
                    
                items = resp.json().get("data", [])
                if not items:
                    break
                    
                for item in items:
                    cat = item.get("category")
                    if cat and isinstance(cat, dict):
                        cat_id = cat.get("id")
                        if cat_id and cat_id not in categories:
                            categories[cat_id] = cat
                            
                offset += limit
                page += 1
                
            except Exception:
                break
                
    print(f"\n✅ Found {len(categories)} unique categories after scanning {page-1} pages.")
    
    # Sort by title
    sorted_cats = sorted(categories.values(), key=lambda x: x.get("title", ""))
    
    # Print and Save
    tree_lines = ["categories:"]
    for c in sorted_cats:
        title = c.get("title", "Unnamed")
        cid = c.get("id")
        pid = c.get("parentCategoryId")
        print(f"- {title} (ID: {cid}, Parent: {pid})")
        tree_lines.append(f"  - title: \"{title}\"")
        tree_lines.append(f"    id: {cid}")
        if pid:
            tree_lines.append(f"    parent_id: {pid}")

    filename = "data/sitniks_inferred_tree.yaml"
    os.makedirs("data", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(tree_lines))
        
    print(f"\n💾 Saved tree definition to {filename}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(infer_tree())
