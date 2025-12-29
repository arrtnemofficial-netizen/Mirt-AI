import asyncio
import os
import json
import httpx
from collections import defaultdict
import re

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
OUTPUT_DIR = os.path.join("data", "sitniks_tree")

def sanitize_filename(name):
    """Make a string safe for filenames."""
    # Transliterate basics if needed, or just strip special chars
    s = str(name).strip().replace(" ", "_")
    return re.sub(r'(?u)[^-\w.]', '', s)

async def dump_by_category():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🚀 Starting Organized Dump from {SNITKIX_API_URL}...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Store by category: category_name -> list_of_products
    categories_map = defaultdict(list)
    total_count = 0
    
    async with httpx.AsyncClient(timeout=30) as client:
        limit = 50
        offset = 0
        page = 1
        
        while True:
            params = {"limit": limit, "offset": offset}
            print(f"📄 Processing Page {page} (Offset {offset})...", end="\r")
            
            try:
                url = f"{SNITKIX_API_URL}/open-api/products"
                resp = await client.get(url, headers=headers, params=params)
                
                if resp.status_code != 200:
                    print(f"\n❌ Error on page {page}: {resp.status_code}")
                    break
                
                data = resp.json()
                items = data.get("data", [])
                
                if not items:
                    print(f"\n🏁 Finished! Reached end of data at page {page}.")
                    break
                
                for item in items:
                    # Extract category title
                    cat_info = item.get("category")
                    if cat_info and isinstance(cat_info, dict):
                        cat_title = cat_info.get("title", "Uncategorized")
                    else:
                        cat_title = "Uncategorized"
                    
                    categories_map[cat_title].append(item)
                    total_count += 1
                
                if len(items) < limit:
                    print(f"\n🏁 Finished! Last page had {len(items)} items.")
                    break
                    
                offset += limit
                page += 1
                
                # Safety break (User said ~200 pages, let's allow 500)
                if page > 500:
                    print("\n⚠️ Safety Limit (500 pages) reached.")
                    break
                    
            except Exception as e:
                print(f"\n❌ Exception: {e}")
                break
    
    print(f"\n\n📦 Organizing {total_count} products into folders...")
    
    # Clean output dir
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    summary = []
    
    for cat_name, products in categories_map.items():
        safe_cat = sanitize_filename(cat_name)
        cat_dir = os.path.join(OUTPUT_DIR, safe_cat)
        os.makedirs(cat_dir, exist_ok=True)
        
        # Save one big JSON for the category
        json_path = os.path.join(cat_dir, f"{safe_cat}_full.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
            
        # Also create a SUMMARY YAML for easy reading
        yaml_lines = _make_yaml_summary(products)
        yaml_path = os.path.join(cat_dir, f"{safe_cat}_summary.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(yaml_lines))
            
        print(f"   📂 {cat_name}: {len(products)} items -> {cat_dir}")
        summary.append(f"- {cat_name}: {len(products)}")

    print("\n✅ Done! Structure:")
    print("\n".join(summary))

def _make_yaml_summary(products):
    lines = ["products:"]
    for p in products:
        name = p.get("title", "No Name")
        lines.append(f"  - name: \"{name}\"")
        lines.append(f"    id: {p.get('id')}")
        vars = p.get("variations", [])
        lines.append(f"    variations: {len(vars)}")
    return lines

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(dump_by_category())
