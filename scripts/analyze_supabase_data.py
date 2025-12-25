#!/usr/bin/env python3
"""
Analyze data in Supabase before migration.

Usage:
    python scripts/analyze_supabase_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.supabase_client import get_supabase_client
from src.conf.config import settings

# Tables to analyze
TABLES = [
    "agent_sessions",
    "messages",
    "users",
    "products",
    "orders",
    "order_items",
    "crm_orders",
    "sitniks_chat_mappings",
    "mirt_profiles",
    "mirt_memories",
    "mirt_memory_summaries",
    "llm_usage",
    "llm_traces",
    "webhook_dedupe",
]


def analyze_table(client, table_name: str) -> dict:
    """Analyze a single table."""
    try:
        # Count records
        response = client.table(table_name).select("id", count="exact").limit(1).execute()
        count = response.count if hasattr(response, "count") else 0
        
        # Get sample record if exists
        sample = None
        if count > 0:
            sample_response = client.table(table_name).select("*").limit(1).execute()
            if sample_response.data:
                sample = sample_response.data[0]
        
        return {
            "table": table_name,
            "count": count,
            "has_sample": sample is not None,
            "sample_keys": list(sample.keys()) if sample else [],
        }
    except Exception as e:
        return {
            "table": table_name,
            "count": None,
            "error": str(e),
        }


def analyze_agent_sessions_structure(client) -> dict:
    """Analyze structure of agent_sessions.state JSONB."""
    try:
        response = (
            client.table("agent_sessions")
            .select("session_id, state")
            .limit(5)
            .execute()
        )
        
        if not response.data:
            return {"samples": [], "state_keys": []}
        
        samples = []
        state_keys = set()
        
        for row in response.data:
            state = row.get("state", {})
            if isinstance(state, dict):
                state_keys.update(state.keys())
                samples.append({
                    "session_id": row.get("session_id"),
                    "state_keys": list(state.keys()),
                    "has_messages": "messages" in state,
                    "has_metadata": "metadata" in state,
                    "current_state": state.get("current_state"),
                })
        
        return {
            "samples": samples,
            "state_keys": sorted(state_keys),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 60)
    print("Supabase Data Analysis")
    print("=" * 60)
    print()
    
    client = get_supabase_client()
    if not client:
        print("❌ Supabase client not available")
        print("   Set SUPABASE_URL and SUPABASE_API_KEY in environment")
        sys.exit(1)
    
    print("✅ Connected to Supabase")
    print()
    
    # Analyze all tables
    print("📊 Analyzing tables...")
    print()
    
    results = []
    total_records = 0
    
    for table in TABLES:
        result = analyze_table(client, table)
        results.append(result)
        
        if result.get("count") is not None:
            count = result["count"]
            total_records += count
            status = "✅" if count > 0 else "⚪"
            print(f"{status} {table:30} {count:>10} records")
        else:
            print(f"❌ {table:30} ERROR: {result.get('error', 'Unknown')}")
    
    print()
    print(f"📈 Total records: {total_records:,}")
    print()
    
    # Analyze agent_sessions structure
    print("🔍 Analyzing agent_sessions.state structure...")
    print()
    
    structure = analyze_agent_sessions_structure(client)
    
    if "error" in structure:
        print(f"❌ Error: {structure['error']}")
    else:
        print(f"✅ Found {len(structure['samples'])} sample sessions")
        print(f"   State keys: {', '.join(structure['state_keys'][:10])}")
        if len(structure['state_keys']) > 10:
            print(f"   ... and {len(structure['state_keys']) - 10} more")
        print()
        
        if structure['samples']:
            print("Sample session structure:")
            sample = structure['samples'][0]
            for key, value in sample.items():
                print(f"   {key}: {value}")
    
    print()
    print("=" * 60)
    print("✅ Analysis complete")
    print("=" * 60)
    
    # Save results to file
    import json
    output_file = Path(__file__).parent / "supabase_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "tables": results,
            "total_records": total_records,
            "agent_sessions_structure": structure,
        }, f, indent=2, default=str)
    
    print(f"📄 Results saved to: {output_file}")


if __name__ == "__main__":
    main()

