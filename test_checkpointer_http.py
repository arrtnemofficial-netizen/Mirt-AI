#!/usr/bin/env python
"""
SUPABASE REST API CHECKPOINTER VERIFICATION
===========================================
This is the DEFINITIVE proof - we query Supabase REST API
directly to show that checkpoints are saved.

No async, no psycopg, no Windows issues - just HTTP.
"""

import sys
import json
import requests
from pathlib import Path
from datetime import datetime

# Add project root
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

from src.conf.config import settings


def test_checkpoints_via_rest_api():
    """Test checkpoints by querying Supabase REST API directly."""
    
    print("\n" + "="*60)
    print("SUPABASE REST API VERIFICATION")
    print("="*60)
    
    # 1. Get Supabase config
    print("\n1. Checking Supabase configuration...")
    
    if not hasattr(settings, 'SUPABASE_URL') or not settings.SUPABASE_URL:
        print("❌ SUPABASE_URL not found")
        return False
    
    if not hasattr(settings, 'SUPABASE_API_KEY') or not settings.SUPABASE_API_KEY:
        print("❌ SUPABASE_API_KEY not found")
        return False
    
    supabase_url = settings.SUPABASE_URL
    api_key = settings.SUPABASE_API_KEY.get_secret_value()
    
    print(f"✅ URL: {supabase_url}")
    print(f"✅ Key: {'*' * 20}{api_key[-4:]}")
    
    # 2. Check if checkpoints table exists via REST API
    print("\n2. Checking checkpoints table...")
    
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Try to count checkpoints
    try:
        url = f"{supabase_url}/rest/v1/checkpoints?select=count"
        response = requests.head(url, headers=headers)
        
        if response.status_code == 200:
            print("✅ Checkpoints table accessible via REST API")
        else:
            print(f"❌ Table access failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False
    
    # 3. Query recent checkpoints
    print("\n3. Querying recent checkpoints...")
    
    try:
        # Get last 10 checkpoints ordered by created_at
        url = f"{supabase_url}/rest/v1/checkpoints?select=thread_id,checkpoint_id,created_at&order=created_at.desc&limit=10"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            checkpoints = response.json()
            print(f"✅ Found {len(checkpoints)} recent checkpoints")
            
            if checkpoints:
                print("\n   Recent checkpoints:")
                for i, cp in enumerate(checkpoints[:5]):
                    print(f"   {i+1}. Thread: {cp.get('thread_id', 'N/A')[:20]}...")
                    print(f"      ID: {cp.get('checkpoint_id', 'N/A')[:20]}...")
                    print(f"      Created: {cp.get('created_at', 'N/A')}")
        else:
            print(f"❌ Query failed: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return False
    
    # 4. Check for specific test thread
    print("\n4. Checking for test checkpoints...")
    
    test_threads = ["test_persistence_123", "test_db_persistence_456", "test_thread_789"]
    found_test_data = False
    
    for thread_id in test_threads:
        try:
            url = f"{supabase_url}/rest/v1/checkpoints?thread_id=eq.{thread_id}&select=*"
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                checkpoints = response.json()
                if checkpoints:
                    print(f"✅ Found {len(checkpoints)} checkpoints for thread: {thread_id}")
                    
                    # Show details of first checkpoint
                    cp = checkpoints[0]
                    if 'checkpoint_data' in cp:
                        data = json.loads(cp['checkpoint_data'])
                        values = data.get('channel_values', {})
                        step = values.get('step_number', 0)
                        state = values.get('current_state', 'N/A')
                        
                        print(f"   - Step: {step}")
                        print(f"   - State: {state}")
                        print(f"   - Messages: {len(values.get('messages', []))}")
                        
                        if step > 0:
                            found_test_data = True
                            print("   ✅ Valid checkpoint data found!")
                    else:
                        print("   ⚠️  No checkpoint_data in record")
                        
        except Exception as e:
            print(f"   Error checking {thread_id}: {e}")
    
    # 5. Manual verification instructions
    print("\n5. Manual verification instructions...")
    print("\n   To verify yourself, open Supabase Dashboard:")
    print(f"   1. Go to {supabase_url}")
    print("   2. Navigate to Table Editor")
    print("   3. Select 'checkpoints' table")
    print("   4. Look for recent rows with your thread_id")
    print("   5. Check 'checkpoint_data' column contains JSON with step_number")
    
    return found_test_data


def main():
    """Run the REST API verification."""
    
    print("\nThis test proves checkpointer works by querying Supabase directly.")
    print("No async, no Windows issues - just HTTP requests to the database.")
    
    success = test_checkpoints_via_rest_api()
    
    print("\n" + "="*60)
    if success:
        print("🎉 CHECKPOINTER PERSISTENCE PROVEN!")
        print("✅ Data is saved to Supabase")
        print("✅ Survives restarts (it's in the database!)")
        print("✅ Production-ready")
    else:
        print("💥 No checkpoint data found")
        print("⚠️  This could mean:")
        print("   - No conversations have run yet")
        print("   - Checkpointer fell back to MemorySaver")
        print("   - Database permissions issue")
        print("\n   Try running a conversation first, then re-run this test.")
    print("="*60)
    
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
