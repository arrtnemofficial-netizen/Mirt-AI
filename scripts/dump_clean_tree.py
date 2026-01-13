import asyncio
import os
import json
import httpx
from collections import defaultdict
import re

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
OUTPUT_DIR = os.path.join("data", "sitniks_tree_final")

def sanitize_filename(name):
    """Make a string safe for filenames."""
    s = str(name).strip().replace(" ", "_").replace("/", "-")
    return re.sub(r'(?u)[^-\w.]', '', s)

def clean_product_data(raw_item):
    """Transform raw Sitniks product into clean, aggregated format."""
    title = raw_item.get("title", "Unknown").strip()
    pid = raw_item.get("id")
    
    # 1. Process Variations to extract Colors, Sizes, Prices
    variations = raw_item.get("variations", [])
    
    colors = set()
    sizes = set()
    price_map = {} # size -> price
    sku_map = {}   # size -> sku (or color+size -> sku)
    photos = []
    
    base_price = 0
    
    for v in variations:
        if not v.get("isActive", True):
            continue
            
        # Price
        price = v.get("price", 0)
        if base_price == 0:
            base_price = price
            
        # Properties
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
            # Record price for this size
            if v_size not in price_map:
                price_map[v_size] = price
            elif price_map[v_size] != price:
                # If same size has diff prices (e.g. valid for diff colors?), keep highest or denote range?
                # For now, simplistic approach: last wins or keep max
                price_map[v_size] = max(price_map[v_size], price)
                
        # Photos
        for att in v.get("attachments", []):
            url = att.get("url")
            if url and url not in photos:
                photos.append(url)
                
    # Determine if we have "Price by Size"
    is_variable_price = False
    if len(set(price_map.values())) > 1:
        is_variable_price = True
        
    # Construct Clean Object
    clean = {
        "id": pid,
        "name": title,
        "base_price": base_price,
        "colors": sorted(list(colors)),
        "sizes": sorted(list(sizes), key=lambda x: str(x)), # Simple sort
        "photo_count": len(photos),
        "main_photo": photos[0] if photos else None
    }
    
    if is_variable_price:
        clean["price_by_size"] = price_map
    else:
        clean["price_by_size"] = "SAME_AXROSS_ALL_SIZES"
        
    return clean

async def dump_clean_tree():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🚀 Starting Clean Dump (Aggregation Mode)...")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    # Store by category
    categories_map = defaultdict(list)
    total_count = 0
    
    async with httpx.AsyncClient(timeout=45) as client: # Increased timeout
        limit = 50
        offset = 0
        page = 1
        
        while True:
            params = {"limit": limit, "offset": offset}
            print(f"📄 Scanning Page {page} (Offset {offset})...", end="\r")
            
            try:
                url = f"{SNITKIX_API_URL}/open-api/products"
                resp = await client.get(url, headers=headers, params=params)
                
                if resp.status_code != 200:
                    print(f"\n❌ Error on page {page}: {resp.status_code}")
                    break
                
                data = resp.json()
                items = data.get("data", [])
                
                if not items:
                    print(f"\n🏁 Reached end of data at page {page}.")
                    break
                
                for item in items:
                    # Categorize
                    cat_info = item.get("category")
                    cat_title = "Uncategorized"
                    if cat_info and isinstance(cat_info, dict):
                        cat_title = cat_info.get("title", "Uncategorized")
                    
                    # CLEAN!
                    clean_item = clean_product_data(item)
                    categories_map[cat_title].append(clean_item)
                    total_count += 1
                
                if len(items) < limit:
                    break
                    
                offset += limit
                page += 1
                
                # Safety Limit increased to 5000 pages (250k items) effectively unlimited for this case
                if page > 5000:
                    break
                    
            except Exception as e:
                print(f"\n❌ Exception: {e}")
                # Retry logic could go here, but for now just break safely
                break
    
    print(f"\n\n📦 Writing {total_count} clean products to {OUTPUT_DIR}...")
    
    # Write Files
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    for cat_name, products in categories_map.items():
        safe_cat = sanitize_filename(cat_name)
        cat_dir = os.path.join(OUTPUT_DIR, safe_cat)
        os.makedirs(cat_dir, exist_ok=True)
        
        # Sort products by name
        products.sort(key=lambda x: x['name'])
        
        # 1. YAML Dump (Beautiful)
        yaml_lines = _to_yaml_string(products)
        yaml_path = os.path.join(cat_dir, "products.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(yaml_lines)
            
        print(f"   📂 {cat_name}: {len(products)} products -> {yaml_path}")

    print("\n✅ DONE! All noisy variations are gone. Pure data remaining.")

def _to_yaml_string(products):
    """Manual simple YAML dumper to ensure BEAUTIFUL formatting."""
    lines = []
    
    for p in products:
        lines.append(f"- name: \"{p['name']}\"")
        lines.append(f"  id: {p['id']}")
        
        # Price
        if p['price_by_size'] == "SAME_AXROSS_ALL_SIZES":
             lines.append(f"  price: {p['base_price']}")
        else:
             lines.append(f"  base_price: {p['base_price']}")
             lines.append(f"  price_per_size:")
             for s, pr in p['price_by_size'].items():
                 lines.append(f"    \"{s}\": {pr}")
                 
        # Sizes
        if p['sizes']:
            lines.append("  sizes:")
            for s in p['sizes']:
                lines.append(f"    - \"{s}\"")
        else:
            lines.append("  sizes: []")
            
        # Colors
        if p['colors']:
            lines.append("  colors:")
            for c in p['colors']:
                lines.append(f"    - \"{c}\"")
        else:
            lines.append("  colors: []")
            
        # Photo
        if p['main_photo']:
            lines.append(f"  image: \"{p['main_photo']}\"")
        
        lines.append("") # Separator
        
    return "\n".join(lines)

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(dump_clean_tree())
