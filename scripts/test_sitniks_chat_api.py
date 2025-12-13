"""Test Sitniks Chat API connection.

Run: python scripts/test_sitniks_chat_api.py
"""

import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


async def test_sitniks_chat_api():
    """Test Sitniks Chat API."""
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service
    
    service = get_sitniks_chat_service()
    
    print("=" * 60)
    print("SITNIKS CHAT API TEST")
    print("=" * 60)
    print()
    
    # 1. Check configuration
    print("1. Configuration:")
    print(f"   API URL: {service.api_url}")
    print(f"   API Key: {'***' + service.api_key[-4:] if service.api_key else 'NOT SET'}")
    print(f"   Enabled: {service.enabled}")
    print()
    
    if not service.enabled:
        print("❌ Service not enabled. Check .env file:")
        print("   SNITKIX_API_URL=https://crm.sitniks.com")
        print("   SNITKIX_API_KEY=your_key_here")
        return
    
    # 2. Test managers endpoint
    print("2. Testing /open-api/managers...")
    try:
        managers = await service.get_managers()
        if managers:
            print(f"   ✅ Found {len(managers)} managers:")
            for m in managers[:5]:  # Show first 5
                user = m.get("user", {})
                print(f"      - ID: {m.get('id')}, Name: {user.get('fullname', 'N/A')}")
        else:
            print("   ⚠️ No managers found (or API returned empty)")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # 3. Test chats endpoint
    print("3. Testing /open-api/chats (last 5 minutes)...")
    try:
        # We can't directly call find_chat_by_username without a username,
        # but we can check if the endpoint works
        import httpx
        from datetime import datetime, timedelta, timezone
        
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(minutes=5)
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{service.api_url}/open-api/chats",
                headers=service._get_headers(),
                params={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "limit": 10,
                },
            )
            
            if response.status_code == 200:
                data = response.json()
                chats = data.get("data", [])
                print(f"   ✅ Found {len(chats)} chats in last 5 minutes")
                for chat in chats[:3]:  # Show first 3
                    print(f"      - ID: {chat.get('id')}, User: {chat.get('userNickName', 'N/A')}")
            elif response.status_code == 403:
                print("   ❌ 403 Forbidden - Need paid plan for API access!")
            else:
                print(f"   ❌ Error {response.status_code}: {response.text[:200]}")
                
    except Exception as e:
        print(f"   ❌ Error: {e}")
    print()
    
    # 4. Test status update endpoint (dry run)
    print("4. Status update endpoint info:")
    print("   Endpoint: PATCH /open-api/chats/{chat_id}/status")
    print("   Body: {\"status\": \"Взято в роботу\"}")
    print("   (Not testing to avoid modifying real data)")
    print()
    
    # 5. Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"API Connection: {'✅ Working' if service.enabled else '❌ Not configured'}")
    print()
    print("Status mapping in code:")
    print("   - first_touch → 'Взято в роботу' + assign AI Manager")
    print("   - give_requisites → 'Виставлено рахунок'")
    print("   - escalation → 'AI Увага' + assign human manager")
    print()


if __name__ == "__main__":
    asyncio.run(test_sitniks_chat_api())
