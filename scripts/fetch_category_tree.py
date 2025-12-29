import asyncio
import os
import json
import httpx

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")

async def explore_categories():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🌳 Probing Category Endpoints at {SNITKIX_API_URL}...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    endpoints = [
        "/open-api/categories",
        "/open-api/catalog/categories",
        "/open-api/product-categories",
        "/open-api/settings/categories",
    ]
    
    async with httpx.AsyncClient(timeout=10) as client:
        found_endpoint = False
        
        for ep in endpoints:
            url = f"{SNITKIX_API_URL}{ep}"
            print(f"🔎 Trying GET {url}...", end=" ")
            try:
                resp = await client.get(url, headers=headers)
                print(f"Status: {resp.status_code}")
                
                if resp.status_code == 200:
                    data = resp.json()
                    print("   ✅ SUCCESS! Found categories.")
                    
                    # Analyze structure
                    items = data.get("data", [])
                    print(f"   Items found: {len(items)}")
                    if items:
                        print(f"   Sample keys: {items[0].keys()}")
                        
                    # Save Tree
                    filename = "data/sitniks_category_tree_raw.json"
                    os.makedirs("data", exist_ok=True)
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"   💾 Saved raw tree to {filename}")
                    
                    # Analyze Hierarchy
                    _analyze_tree_structure(items)
                    found_endpoint = True
                    break
                    
            except Exception as e:
                print(f"\n   ❌ Exception: {e}")
        
        if not found_endpoint:
            print("\n❌ No dedicated category endpoint found.")
            print("   We might need to infer the tree from products (slower), or the endpoint is named differently.")

def _analyze_tree_structure(items):
    """Print a simple visualized tree if parentId exists."""
    # Map ID -> Item
    id_map = {item.get("id"): item for item in items}
    
    # Build Children Map
    children_map = defaultdict(list)
    roots = []
    
    for item in items:
        pid = item.get("parentCategoryId")
        if pid and pid in id_map:
            children_map[pid].append(item)
        else:
            roots.append(item)
            
    print("\n🌳 CATEGORY TREE PREVIEW:\n")
    for root in roots:
        _print_node(root, children_map)

def _print_node(node, children_map, level=0):
    indent = "  " * level
    title = node.get("title", "Unnamed")
    cid = node.get("id")
    print(f"{indent}- {title} (ID: {cid})")
    
    for child in children_map.get(cid, []):
        _print_node(child, children_map, level + 1)

from collections import defaultdict

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(explore_categories())
