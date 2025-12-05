import asyncio
import argparse
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.supabase_client import get_supabase_client
from src.core.logging import setup_logging

async def diagnose(session_id: str):
    """Fetch and print traces for a session."""
    client = get_supabase_client()
    if not client:
        print("❌ Supabase client not configured.")
        return

    print(f"🔍 Diagnosing session: {session_id}")
    
    # Fetch traces
    response = await client.table("llm_traces")\
        .select("*")\
        .eq("session_id", session_id)\
        .order("created_at", desc=False)\
        .execute()
    
    traces = response.data
    
    if not traces:
        print("⚠️ No traces found for this session.")
        return

    print(f"found {len(traces)} steps.\n")
    
    for t in traces:
        ts = datetime.fromisoformat(t["created_at"]).strftime("%H:%M:%S")
        status_icon = "✅" if t["status"] == "SUCCESS" else "❌"
        if t["status"] == "BLOCKED": status_icon = "🚫"
        if t["status"] == "ESCALATED": status_icon = "⚠️"
        
        node = t["node_name"].ljust(15)
        state = (t["state_name"] or "-").ljust(20)
        prompt = t["prompt_key"] or "-"
        
        print(f"{ts} {status_icon} | {node} | {state} | {prompt}")
        
        if t["status"] != "SUCCESS":
            print(f"   🟥 Error: {t['error_category']} - {t['error_message']}")
        
        if t["latency_ms"]:
            print(f"   ⏱️ {t['latency_ms']}ms")
            
        print("-" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose AI conversation")
    parser.add_argument("session_id", help="Session ID (Telegram ID)")
    asyncio.run(diagnose(parser.parse_args().session_id))
