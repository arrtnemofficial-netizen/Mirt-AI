
import asyncio
import os
import json
import httpx
import yaml
from collections import defaultdict
import re
from pathlib import Path
import time

# Configuration
def load_env():
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
COMPANY_ID = "4588" 
OUTPUT_DIR = Path("data/sitniks_tree_final")

# Safety Header
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def sanitize_filename(name):
    """Make a string safe for filenames."""
    s = str(name).strip().replace(" ", "_").replace("/", "-")
    return re.sub(r'(?u)[^-\w.]', '', s)

def aggregate_product_data(raw_item):
    """Aggregate variations into a single clean product object."""
    title = raw_item.get("title", "Unknown").strip()
    pid = raw_item.get("id")
    
    variations = raw_item.get("variations", [])
    
    colors = set()
    sizes = set()
    photos = []
    
    price_map = {} # size -> price
    color_images = {} # color -> image_url
    base_price = 0
    
    for v in variations:
        if not v.get("isActive", True):
            continue
            
        price = v.get("price", 0)
        if base_price == 0:
            base_price = price
            
        # Determine Color and Size for this variation
        current_color = None
        
        for prop in v.get("properties", []):
            p_name = prop.get("name", "").lower()
            p_val = str(prop.get("value", "")).strip()
            
            if not p_val:
                continue
                
            if any(kw in p_name for kw in ["колір", "цвет", "color"]):
                colors.add(p_val)
                current_color = p_val
            elif any(kw in p_name for kw in ["розмір", "размер", "size"]):
                # Clean size string
                p_val = p_val.replace(" / ", "-").replace("/", "-").replace(" ", "")
                sizes.add(p_val)
                if p_val not in price_map:
                    price_map[p_val] = price
                else:
                    price_map[p_val] = max(price_map[p_val], price)
        
        # Attachments (Photos) - Link to color if found
        for att in v.get("attachments", []):
            url = att.get("url")
            if url:
                if url not in photos:
                    photos.append(url)
                # If this variation had a color, link the photo to it
                if current_color and current_color not in color_images:
                    color_images[current_color] = url
                
    is_variable_price = len(set(price_map.values())) > 1
    
    clean = {
        "name": title,
        "id": pid,
        "price": base_price,
        "sizes": sorted(list(sizes)),
        "colors": sorted(list(colors)),
        "image": photos[0] if photos else None,
    }
    
    if is_variable_price:
        clean["price_per_size"] = dict(sorted(price_map.items()))
        
    if color_images:
        clean["color_images"] = dict(sorted(color_images.items()))
        
    return clean

async def scrape_optimized():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is missing.")
        return

    print(f"🚀 Starting SAFE & OPTIMIZED Scrape from {SNITKIX_API_URL}...")
    print(f"🛠️  Company ID: {COMPANY_ID} | Delay: 3.0s | Retries: 3")
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "X-Company-Id": COMPANY_ID,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    seen_ids = set()
    categories_data = defaultdict(list)
    total_unique = 0
    
    async with httpx.AsyncClient(timeout=60) as client:
        limit = 50
        offset = 0
        page = 1
        
        while True:
            params = {"limit": limit, "offset": offset}
            print(f"📄 Page {page} (Offset {offset}) | Found: {total_unique}...")
            
            retry_count = 0
            max_retries = 3
            resp = None
            
            while retry_count < max_retries:
                try:
                    resp = await client.get(f"{SNITKIX_API_URL}/open-api/products", headers=headers, params=params)
                    if resp.status_code == 200:
                        break
                    elif resp.status_code == 429:
                        print(f"⚠️ Rate limited (429)! Waiting 15s...")
                        await asyncio.sleep(15)
                    else:
                        print(f"⚠️ API Error {resp.status_code}. Retrying ({retry_count+1}/{max_retries})...")
                        await asyncio.sleep(5)
                except Exception as e:
                    print(f"⚠️ Request exception: {e}. Retrying...")
                    await asyncio.sleep(5)
                retry_count += 1
            
            if not resp or resp.status_code != 200:
                print(f"❌ Critical Failure: Could not fetch page {page}.")
                break
                
            data = resp.json()
            items = data.get("data", [])
            
            if not items:
                print(f"🏁 End of data reached.")
                break
            
            for item in items:
                pid = item.get("id")
                if pid in seen_ids:
                    continue
                
                seen_ids.add(pid)
                total_unique += 1
                
                cat_info = item.get("category")
                cat_title = "Uncategorized"
                if cat_info and isinstance(cat_info, dict):
                    cat_title = cat_info.get("title", "Uncategorized")
                
                clean_item = aggregate_product_data(item)
                categories_data[cat_title].append(clean_item)
            
            if len(items) < limit:
                break
                
            offset += limit
            page += 1
            
            # --- MAXIMUM SAFETY DELAY ---
            print(f"⏳ Sleeping 3.0s...")
            await asyncio.sleep(3.0)
            
    # Save Results
    print(f"\n📦 Saving results to {OUTPUT_DIR}...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    for cat_name, products in categories_data.items():
        safe_cat = sanitize_filename(cat_name)
        cat_dir = OUTPUT_DIR / safe_cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        
        products.sort(key=lambda x: x['name'])
        
        yaml_path = cat_dir / "products.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(products, f, allow_unicode=True, sort_keys=False, indent=2, default_flow_style=False)
            
        print(f"   ✅ Saved {len(products)} products to '{cat_name}'")

    print(f"\n🎉 DONE! Total {total_unique} unique products processed.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scrape_optimized())
