import asyncio
import os
import json
import httpx
from collections import defaultdict
import re

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
OUTPUT_DIR = os.path.join("data", "sitniks_tree_active")

def sanitize_filename(name):
    s = str(name).strip().replace(" ", "_").replace("/", "-")
    return re.sub(r'(?u)[^-\w.]', '', s)

def clean_product_data(raw_item):
    """Clean ACTIVE product data."""
    # First check: Is the product itself active?
    # Note: API structure might have 'isActive' at root or only in variations?
    # Sample showed 'variations' have 'isActive', but root didn't show 'isActive' in the snippet I saw?
    # Let's check sample keys again. Sample had: id, title, category... 
    # Wait, sample snippet line 28 was INSIDE a variation. 
    # Let's assume validation needs to check if ANY variation is active.
    
    variations = raw_item.get("variations", [])
    active_variations = [v for v in variations if v.get("isActive")]
    
    if not active_variations:
        return None # No active variations -> Product is effectively inactive/sold out
        
    title = raw_item.get("title", "Unknown").strip()
    pid = raw_item.get("id")
    
    colors = set()
    sizes = set()
    price_map = {} 
    photos = []
    base_price = 0
    
    for v in active_variations:
        price = v.get("price", 0)
        if base_price == 0:
            base_price = price
            
        v_color = None
        v_size = None
        
        for prop in v.get("properties", []):
            p_name = prop.get("name", "").lower()
            p_val = prop.get("value", "")
            if "колір" in p_name or "цвет" in p_name:
                v_color = p_val
            elif "розмір" in p_name or "размер" in p_name:
                v_size = p_val
                
        if v_color:
            colors.add(v_color)
        if v_size:
            sizes.add(v_size)
            price_map[v_size] = price
                
        for att in v.get("attachments", []):
            url = att.get("url")
            if url and url not in photos:
                photos.append(url)
                
    clean = {
        "id": pid,
        "name": title,
        "base_price": base_price,
        "colors": sorted(list(colors)),
        "sizes": sorted(list(sizes), key=lambda x: str(x)),
        "photo_count": len(photos),
        "main_photo": photos[0] if photos else None,
        "price_by_size": price_map if len(set(price_map.values())) > 1 else "SAME"
    }
    return clean

async def dump_active():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY missing.")
        return

    print(f"🚀 Dumping ONLY ACTIVE Items (Matching your ~198 pages)...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # We will write to distinct files per category AS WE GO to avoid memory issues
    # But we need to keep track of what we opened
    # Actually, simpler: Collect in memory, but write every 10 pages?
    # Or just Append? YAML is hard to append nicely without structure.
    # Let's stick to Memory -> Write at end, BUT with strict "Active" filtering, 
    # the dataset should be 10x smaller (only 10k items), which fits easily in RAM.
    
    categories_map = defaultdict(list)
    total_active_count = 0
    total_scanned = 0
    
    async with httpx.AsyncClient(timeout=45) as client:
        limit = 50 
        offset = 0
        page = 1
        
        while True:
            params = {"limit": limit, "offset": offset}
            print(f"📄 Page {page} | Active Found: {total_active_count} | Scanned: {total_scanned}", end="\r")
            
            try:
                url = f"{SNITKIX_API_URL}/open-api/products"
                resp = await client.get(url, headers=headers, params=params)
                
                if resp.status_code != 200:
                    print(f"\n❌ Error on page {page}: {resp.status_code}")
                    break
                
                data = resp.json()
                items = data.get("data", [])
                
                if not items:
                    print(f"\n🏁 Finished. Scanned {total_scanned} items.")
                    break
                    
                total_scanned += len(items)
                
                for item in items:
                    clean = clean_product_data(item)
                    if clean:
                        # IT IS ACTIVE! Adding.
                        cat_info = item.get("category")
                        cat_title = "Uncategorized"
                        if cat_info and isinstance(cat_info, dict):
                            cat_title = cat_info.get("title", "Uncategorized")
                        
                        categories_map[cat_title].append(clean)
                        total_active_count += 1
                
                if len(items) < limit:
                    break
                    
                offset += limit
                page += 1
                
                # Safety Limit
                if page > 5000:
                    break
                    
            except Exception as e:
                print(f"\n❌ Exception: {e}")
                break
                
    print(f"\n\n📦 Saving {total_active_count} ACTIVE products...")
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for cat_name, products in categories_map.items():
        if not products:
            continue
            
        safe_cat = sanitize_filename(cat_name)
        cat_dir = os.path.join(OUTPUT_DIR, safe_cat)
        os.makedirs(cat_dir, exist_ok=True)
        
        products.sort(key=lambda x: x['name'])
        
        yaml_lines = _to_yaml_string(products)
        yaml_path = os.path.join(cat_dir, "products.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_lines)
            
        print(f"   📂 {cat_name}: {len(products)} products")

    print(f"\n✅ DONE. Saved to {OUTPUT_DIR}")

def _to_yaml_string(products):
    lines = []
    for p in products:
        lines.append(f"- name: \"{p['name']}\"")
        lines.append(f"  id: {p['id']}")
        
        if p['price_by_size'] == "SAME":
             lines.append(f"  price: {p['base_price']}")
        else:
             lines.append(f"  base_price: {p['base_price']}")
             lines.append(f"  price_per_size:")
             for s, pr in p['price_by_size'].items():
                 lines.append(f"    \"{s}\": {pr}")
                 
        if p['sizes']:
            lines.append("  sizes:")
            for s in p['sizes']:
                lines.append(f"    - \"{s}\"")
        if p['colors']:
            lines.append("  colors:")
            for c in p['colors']:
                lines.append(f"    - \"{c}\"")
                
        if p['main_photo']:
            lines.append(f"  image: \"{p['main_photo']}\"")
        
        lines.append("")
    return "\n".join(lines)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(dump_active())
