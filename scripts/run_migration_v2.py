"""Update product descriptions with closure type info."""

import sys


sys.path.insert(0, ".")

from src.services.supabase_client import get_supabase_client


client = get_supabase_client()
if not client:
    print("❌ Supabase client not available")
    sys.exit(1)

print("🔄 Updating product descriptions with closure info...")

# Get all Лагуна products
laguna = (
    client.table("products")
    .select("id, name, description")
    .like("name", "Костюм Лагуна%")
    .execute()
)
for p in laguna.data:
    new_desc = (
        f"{p.get('description', '')} [ЗАСТІБКА: ПОВНА блискавка від горла до низу. МАТЕРІАЛ: плюш]"
    )
    client.table("products").update({"description": new_desc}).eq("id", p["id"]).execute()
    print(f"✅ {p['name']}: full_zip")

# Get all Мрія products
mriya = (
    client.table("products").select("id, name, description").like("name", "Костюм Мрія%").execute()
)
for p in mriya.data:
    new_desc = f"{p.get('description', '')} [ЗАСТІБКА: HALF-ZIP (коротка блискавка до грудей). МАТЕРІАЛ: плюш]"
    client.table("products").update({"description": new_desc}).eq("id", p["id"]).execute()
    print(f"✅ {p['name']}: half_zip")

print(f"\n✅ Updated {len(laguna.data)} Лагуна + {len(mriya.data)} Мрія products!")
print("\nВерифікація:")
verify = (
    client.table("products")
    .select("name, description")
    .or_("name.like.Костюм Лагуна%,name.like.Костюм Мрія%")
    .execute()
)
for p in verify.data:
    desc = p.get("description", "")[:100]
    print(f"  {p['name']}: {desc}...")
