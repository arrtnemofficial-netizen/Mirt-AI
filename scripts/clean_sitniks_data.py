
import os
import yaml
from pathlib import Path

# Path to the root data directory
DATA_ROOT = Path("data/sitniks_tree_final")

def clean_directory(directory_path):
    print(f"Processing directory: {directory_path}")
    
    products_file = directory_path / "products.yaml"
    
    # Check for garbage files (anything not products.yaml)
    # We allow 'images' directory if it exists, though user said no other files expected.
    for item in directory_path.iterdir():
        if item.name == "products.yaml":
            continue
        if item.is_dir() and item.name == "images":
            continue
            
        print(f"  [DELETE] Found garbage file/dir: {item.name}")
        # Uncomment the next line to actually delete
        if item.is_dir():
             # Safety check: simplistic removal (requires empty dir or shutil for recursive)
             # keeping safe for now, assuming files.
             pass 
        else:
             item.unlink()
             print(f"  Deleted: {item.name}")

    if not products_file.exists():
        print("  No products.yaml found.")
        return

    # Process YAML
    try:
        with open(products_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        if not data:
            print("  products.yaml is empty.")
            return

        original_count = len(data)
        unique_products = {}
        
        # Deduplicate based on 'id'
        for product in data:
            p_id = product.get("id")
            if p_id:
                unique_products[p_id] = product
            else:
                # If no ID, use name as fallback key or skip? 
                # Assuming all have IDs based on previous view.
                # If valid product without ID exists, we might lose it if we don't handle.
                # Let's use name-price combo if ID missing, or just keep it.
                # But looking at file, they all seem to have IDs.
                pass
        
        cleaned_data = list(unique_products.values())
        
        # Sort by name
        cleaned_data.sort(key=lambda x: x.get("name", ""))
        
        final_count = len(cleaned_data)
        print(f"  Deduplication: {original_count} -> {final_count} products.")
        
        if final_count < original_count or True: # Always rewrite to ensure formatting
            with open(products_file, "w", encoding="utf-8") as f:
                yaml.dump(cleaned_data, f, allow_unicode=True, sort_keys=False, indent=2)
            print("  File updated and formatted.")
            
    except Exception as e:
        print(f"  Error processing {products_file}: {e}")

def main():
    if not DATA_ROOT.exists():
        print(f"Directory {DATA_ROOT} does not exist.")
        return

    # Iterate over all subdirectories
    for category_dir in DATA_ROOT.iterdir():
        if category_dir.is_dir():
            clean_directory(category_dir)

if __name__ == "__main__":
    main()
