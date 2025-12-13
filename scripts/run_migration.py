"""Run SQL migration for closure_type and material."""
import sys
sys.path.insert(0, '.')

from src.services.supabase_client import get_supabase_client

client = get_supabase_client()
if not client:
    print('❌ Supabase client not available')
    sys.exit(1)

print("🔄 Running migration...")

# Update Лагуна (full_zip)
try:
    r1 = client.table('products').update({
        'closure_type': 'full_zip',
        'material': 'плюш',
    }).like('name', 'Костюм Лагуна%').execute()
    print(f'✅ Updated Лагуна: {len(r1.data)} rows (closure_type=full_zip)')
except Exception as e:
    print(f'⚠️ Лагуна update error: {e}')

# Update Мрія (half_zip)  
try:
    r2 = client.table('products').update({
        'closure_type': 'half_zip',
        'material': 'плюш',
    }).like('name', 'Костюм Мрія%').execute()
    print(f'✅ Updated Мрія: {len(r2.data)} rows (closure_type=half_zip)')
except Exception as e:
    print(f'⚠️ Мрія update error: {e}')

# Verify
print("\n📋 Verification:")
try:
    r3 = client.table('products').select('name, closure_type, material, price').or_('name.like.Костюм Лагуна%,name.like.Костюм Мрія%').execute()
    for p in r3.data:
        closure = p.get('closure_type') or '❌ NULL'
        material = p.get('material') or '?'
        print(f"  {p['name']}: {closure} / {material}")
except Exception as e:
    print(f'⚠️ Verify error: {e}')

print("\n✅ Migration complete!")
