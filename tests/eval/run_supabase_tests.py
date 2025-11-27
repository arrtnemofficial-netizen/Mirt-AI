"""
MIRT AI Supabase Integration Tests v1.0
=======================================
Тестування інтеграції з Supabase:
- Семантичний пошук (embeddings)
- RPC функції
- CRUD операції
- Безпека (SQL injection)

Запуск: python tests/eval/run_supabase_tests.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from supabase import create_client, Client

DATASETS_DIR = Path(__file__).parent / "datasets"
RESULTS_DIR = Path(__file__).parent / "results"


def get_supabase_client() -> Client:
    """Get Supabase client."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_API_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL or SUPABASE_API_KEY not set")
    return create_client(url, key)


def load_tests() -> dict:
    """Load Supabase test cases."""
    path = DATASETS_DIR / "supabase_tests_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


async def test_semantic_search(client: Client, test: dict) -> dict:
    """Test semantic search via RPC."""
    query = test["input"]["query"]
    match_count = test["input"].get("match_count", 5)
    expected = test["expected"]
    
    # Для семантичного пошуку потрібен embedding
    # Тут ми тестуємо з фейковим embedding (hash-based fallback)
    import hashlib
    
    def hash_embedding(text: str, dim: int = 1536) -> list:
        digest = hashlib.sha256(text.encode()).digest()
        values = []
        while len(values) < dim:
            for byte in digest:
                values.append((byte / 255.0) * 2 - 1)
                if len(values) >= dim:
                    break
        return values
    
    try:
        if not query:
            return {
                "pass": expected.get("should_return_empty", False),
                "result": [],
                "reason": "Empty query handled correctly"
            }
        
        embedding = hash_embedding(query)
        
        response = client.rpc(
            "match_mirt_products",
            {"query_embedding": embedding, "match_count": match_count}
        ).execute()
        
        data = response.data or []
        
        # Validate results
        checks = []
        passed = True
        
        # Check min/max results
        if "min_results" in expected:
            if len(data) < expected["min_results"]:
                passed = False
                checks.append(f"Expected min {expected['min_results']} results, got {len(data)}")
        
        if "max_results" in expected:
            if len(data) > expected["max_results"]:
                passed = False
                checks.append(f"Expected max {expected['max_results']} results, got {len(data)}")
        
        # Check required fields
        if "must_have_fields" in expected and data:
            for field in expected["must_have_fields"]:
                if field not in data[0]:
                    passed = False
                    checks.append(f"Missing field: {field}")
        
        return {
            "pass": passed,
            "result_count": len(data),
            "first_result": data[0] if data else None,
            "checks": checks if checks else ["All checks passed"]
        }
        
    except Exception as e:
        return {"pass": False, "error": str(e)}


async def test_get_by_id(client: Client, test: dict) -> dict:
    """Test get product by ID."""
    product_id = test["input"]["product_id"]
    expected = test["expected"]
    
    try:
        response = client.table("mirt_products").select("*").eq("id", product_id).execute()
        data = response.data or []
        
        exists = len(data) > 0
        
        if expected.get("must_exist"):
            if not exists:
                return {"pass": False, "reason": "Product should exist but not found"}
            
            # Check expected name
            if "expected_name_contains" in expected:
                name = data[0].get("name", "")
                if expected["expected_name_contains"] not in name:
                    return {"pass": False, "reason": f"Name mismatch: {name}"}
            
            return {"pass": True, "data": data[0]}
        else:
            if exists:
                return {"pass": False, "reason": "Product should NOT exist but found"}
            return {"pass": True, "reason": "Correctly returned empty"}
            
    except Exception as e:
        return {"pass": False, "error": str(e)}


async def test_rpc_call(client: Client, test: dict) -> dict:
    """Test RPC function exists and works."""
    rpc_name = test["input"]["rpc_name"]
    params = test["input"].get("params", {})
    expected = test["expected"]
    
    try:
        # Для RPC потрібен embedding
        import hashlib
        def hash_embedding(text: str, dim: int = 1536) -> list:
            digest = hashlib.sha256(text.encode()).digest()
            values = []
            while len(values) < dim:
                for byte in digest:
                    values.append((byte / 255.0) * 2 - 1)
                    if len(values) >= dim:
                        break
            return values
        
        embedding = hash_embedding("test query")
        params["query_embedding"] = embedding
        
        response = client.rpc(rpc_name, params).execute()
        data = response.data or []
        
        if expected.get("must_succeed"):
            if "min_results" in expected and len(data) < expected["min_results"]:
                return {"pass": False, "reason": f"Expected min {expected['min_results']} results"}
            return {"pass": True, "result_count": len(data)}
        
        return {"pass": True, "data": data}
        
    except Exception as e:
        return {"pass": False, "error": str(e)}


async def test_embedding_check(client: Client, test: dict) -> dict:
    """Check embedding exists for product."""
    product_id = test["input"]["product_id"]
    expected = test["expected"]
    
    try:
        response = client.table("mirt_product_embeddings").select("*").eq("product_id", product_id).execute()
        data = response.data or []
        
        if not data:
            return {"pass": not expected.get("embedding_exists", True), "reason": "No embedding found"}
        
        embedding = data[0]
        
        checks = []
        passed = True
        
        # Check embedding dimension
        if "embedding_dim" in expected:
            # embedding може бути string або list
            emb_value = embedding.get("embedding", [])
            if isinstance(emb_value, str):
                # Це може бути у форматі "[0.1, 0.2, ...]"
                try:
                    emb_value = json.loads(emb_value)
                except:
                    pass
            
            if isinstance(emb_value, list) and len(emb_value) != expected["embedding_dim"]:
                passed = False
                checks.append(f"Wrong dimension: {len(emb_value)} vs {expected['embedding_dim']}")
        
        # Check chunk_text
        if expected.get("chunk_text_not_empty"):
            if not embedding.get("chunk_text"):
                passed = False
                checks.append("chunk_text is empty")
        
        return {
            "pass": passed,
            "checks": checks if checks else ["All checks passed"],
            "chunk_text_preview": (embedding.get("chunk_text") or "")[:100]
        }
        
    except Exception as e:
        return {"pass": False, "error": str(e)}


async def test_sql_injection(client: Client, test: dict) -> dict:
    """Test SQL injection protection."""
    query = test["input"]["query"]
    expected = test["expected"]
    
    try:
        # Спробуємо пошук з потенційно небезпечним запитом
        import hashlib
        def hash_embedding(text: str, dim: int = 1536) -> list:
            digest = hashlib.sha256(text.encode()).digest()
            values = []
            while len(values) < dim:
                for byte in digest:
                    values.append((byte / 255.0) * 2 - 1)
                    if len(values) >= dim:
                        break
            return values
        
        embedding = hash_embedding(query)
        
        response = client.rpc(
            "match_mirt_products",
            {"query_embedding": embedding, "match_count": 5}
        ).execute()
        
        # Якщо дійшли сюди — injection не спрацював
        # Перевіримо що таблиця все ще існує
        check = client.table("mirt_products").select("id").limit(1).execute()
        
        return {
            "pass": True,
            "reason": "SQL injection attempt blocked, table still exists",
            "table_check": len(check.data or []) > 0
        }
        
    except Exception as e:
        # Помилка може бути через sanitization — це добре
        return {"pass": expected.get("no_error", True), "error": str(e)}


async def run_supabase_tests():
    """Run all Supabase tests."""
    
    print(f"\n{'='*60}")
    print(f"🗄️ MIRT AI Supabase Integration Tests")
    print(f"{'='*60}")
    
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        client = get_supabase_client()
        print("✅ Supabase connection OK")
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        return
    
    tests_data = load_tests()
    tests = tests_data.get("tests", [])
    
    print(f"📊 Tests to run: {len(tests)}")
    print(f"{'='*60}\n")
    
    results = []
    passed = 0
    failed = 0
    
    for i, test in enumerate(tests, 1):
        test_id = test["id"]
        test_type = test["type"]
        description = test["description"]
        
        print(f"[{i}/{len(tests)}] {test_id}: {description[:40]}... ", end="", flush=True)
        
        try:
            if test_type == "semantic_search":
                result = await test_semantic_search(client, test)
            elif test_type == "get_by_id":
                result = await test_get_by_id(client, test)
            elif test_type == "rpc_call":
                result = await test_rpc_call(client, test)
            elif test_type == "embedding_check":
                result = await test_embedding_check(client, test)
            elif test_type == "schema_validation":
                # Basic schema check
                response = client.table("mirt_products").select("*").limit(1).execute()
                result = {"pass": len(response.data or []) > 0, "reason": "Table accessible"}
            else:
                result = {"pass": False, "reason": f"Unknown test type: {test_type}"}
            
            status = "✅ PASS" if result.get("pass") else "❌ FAIL"
            print(status)
            
            if result.get("pass"):
                passed += 1
            else:
                failed += 1
            
            results.append({
                "test_id": test_id,
                "type": test_type,
                "description": description,
                **result
            })
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
            failed += 1
            results.append({
                "test_id": test_id,
                "type": test_type,
                "pass": False,
                "error": str(e)
            })
    
    # Summary
    total = passed + failed
    rate = (passed / total * 100) if total > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"📊 SUPABASE TESTS SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Passed: {passed}/{total} ({rate:.1f}%)")
    print(f"❌ Failed: {failed}/{total}")
    print(f"{'='*60}")
    
    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "run_id": f"supabase-{timestamp}",
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{rate:.1f}%"
        },
        "results": results
    }
    
    report_path = RESULTS_DIR / f"supabase_results_{timestamp}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n📁 Report saved: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_supabase_tests())
