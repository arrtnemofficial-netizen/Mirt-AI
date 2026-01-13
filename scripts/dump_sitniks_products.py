import asyncio
import os
import json
import httpx
from datetime import datetime

# Configuration
SNITKIX_API_URL = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
SNITKIX_API_KEY = os.getenv("SNITKIX_API_KEY", "")
DUMP_DIR = os.path.join("data", "sitniks_dump")

async def dump_all_products():
    if not SNITKIX_API_KEY:
        print("❌ SNITKIX_API_KEY is allowed. Set it in env or pass it.")
        return

    print(f"🚀 Starting Sitniks Product Dump...")
    print(f"URL: {SNITKIX_API_URL}")
    
    os.makedirs(DUMP_DIR, exist_ok=True)
    
    headers = {
        "Authorization": f"Bearer {SNITKIX_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    all_products = []
    limit = 50
    offset = 0
    page = 1
    
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params = {
                "limit": limit,
                "offset": offset
            }
            
            print(f"📄 Fetching page {page} (Offset: {offset})...")
            try:
                # Note: Sitniks API might use different pagination keys (offset/limit is standard)
                # If offset doesn't work, we might need to check docs, but let's try standard first.
                url = f"{SNITKIX_API_URL}/open-api/products"
                response = await client.get(url, headers=headers, params=params)
                
                if response.status_code != 200:
                    print(f"❌ Error fetching page {page}: {response.status_code} {response.text[:100]}")
                    break
                
                data = response.json()
                items = data.get("data", [])
                
                if not items:
                    print("🏁 No more items found. Finished.")
                    break
                
                print(f"✅ Got {len(items)} items.")
                all_products.extend(items)
                
                # Check actual pagination logic from response if available
                # Meta usually contains 'total', 'count' etc.
                meta = data.get("meta", {})
                print(f"   Meta: {meta}")
                
                # If we got fewer items than limit, we are done
                if len(items) < limit:
                    break
                    
                offset += limit
                page += 1
                
                # Safety break for huge catalogs to avoid infinite loops during test
                if page > 100: 
                    print("⚠️ Safety Limit reached (100 pages). Stopping.")
                    break
                    
            except Exception as e:
                print(f"❌ Exception: {e}")
                break
    
    # Save Raw Dump
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(DUMP_DIR, f"sitniks_products_full_{timestamp}.json")
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_products, f, ensure_ascii=False, indent=2)
        
    print(f"\n💾 Saved {len(all_products)} products to:")
    print(f"   {filename}")
    
    # Convert to simplified YAML equivalent (Preview)
    yaml_lines = _convert_to_yaml_preview(all_products)
    yaml_filename = os.path.join(DUMP_DIR, f"sitniks_converted_preview_{timestamp}.yaml")
    with open(yaml_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(yaml_lines))
        
    print(f"📝 Saved YAML preview to:")
    print(f"   {yaml_filename}")


def _convert_to_yaml_preview(products):
    """Simple converter to match our products_master.yaml format."""
    lines = ["products:"]
    
    for p in products:
        title = p.get("title", "Unknown").strip()
        slug = _slugify(title)
        
        lines.append(f"  {slug}:")
        lines.append(f"    id: {p.get('id')}")
        lines.append(f"    name: \"{title}\"")
        cat = p.get("category", {}).get("title", "Unknown")
        lines.append(f"    category: \"{cat}\"")
        
        # Prices & Colors aggregation
        # Simplified logic: grab first price
        # Real logic needs to scan all variations
        variations = p.get("variations", [])
        if variations:
            lines.append("    colors:")
            processed_colors = set()
            
            for v in variations:
                # Extract Color
                color_val = "unknown"
                for prop in v.get("properties", []):
                    if prop.get("name") == "колір":
                        color_val = prop.get("value")
                
                if color_val not in processed_colors:
                    sku = v.get("sku", "")
                    # Extract Photo
                    photo = ""
                    attachments = v.get("attachments", [])
                    if attachments:
                        photo = attachments[0].get("url", "")
                        
                    lines.append(f"      {_slugify(color_val)}:")
                    lines.append(f"        display_name: \"{color_val}\"")
                    lines.append(f"        sku: \"{sku}\"")
                    if photo:
                         lines.append(f"        photo_url: \"{photo}\"")
                    
                    processed_colors.add(color_val)
                    
    return lines

def _slugify(text):
    # Very basic slugify for demo
    mapping = {
        "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ye", "ж": "zh", "з": "z",
        "и": "y", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
        "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
        "ю": "yu", "я": "ya", "ь": "", "'": "", " ": "_"
    }
    s = text.lower()
    for k, v in mapping.items():
        s = s.replace(k, v)
    return s

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(dump_all_products())
