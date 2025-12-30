from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header

print("--- Testing Snippet Loading ---")

snippets_checkout = get_snippet_by_header("Підтвердження замовлення")
if snippets_checkout:
    print("✅ Checkout snippet found (length:", len(snippets_checkout), ")")
    print("Preview:", snippets_checkout[0][:100] + "...")
else:
    print("❌ Checkout snippet NOT found!")

snippets_thanks = get_snippet_by_header("Подяка за замовлення")
if snippets_thanks:
    print("✅ Thanks snippet found (length:", len(snippets_thanks), ")")
    print("Preview:", snippets_thanks[0][:50] + "...")
else:
    print("❌ Thanks snippet NOT found!")

snippets_subscribe = get_snippet_by_header("Прохання підписатись (безпека)")
if snippets_subscribe:
    print("✅ Subscribe snippet found (length:", len(snippets_subscribe), ")")
    print("Preview:", snippets_subscribe[0][:50] + "...")
else:
    print("❌ Subscribe snippet NOT found!")
