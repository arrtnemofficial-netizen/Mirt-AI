#!/usr/bin/env python3
"""Test Sitniks CRM API connection and fetch order statuses."""

import json
import os
import sys


# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from dotenv import load_dotenv


load_dotenv()

# Try multiple API keys and URLs
API_KEYS = [
    os.getenv("SNITKIX_API_KEY", ""),
    "XbTkWiJX3BxeCO1HTcm8nudCfeivyML22dJgpUZvimn",  # First key user gave
]

API_URLS = [
    "https://crm.sitniks.com",
    "https://api.sitniks.com",
    "https://api.sitniks.ua",
    "https://web.sitniks.com",
]


def test_connection():
    """Test Sitniks API and get order statuses."""
    print("Testing Sitniks API...")
    print(f"URL: {API_URL}")
    print(f"Key: {API_KEY[:10]}..." if API_KEY else "Key: NOT SET")
    print("=" * 60)

    # Try different auth formats
    auth_formats = [
        {"Authorization": f"Bearer {API_KEY}"},
        {"Authorization": f"Api-Key {API_KEY}"},
        {"Authorization": API_KEY},
        {"X-API-Key": API_KEY},
        {"Api-Key": API_KEY},
        {"api-key": API_KEY},
    ]

    base_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    with httpx.Client(timeout=30) as client:
        # Try each auth format
        url = f"{API_URL}/open-api/orders/statuses"

        for i, auth_header in enumerate(auth_formats, 1):
            headers = {**base_headers, **auth_header}
            auth_type = list(auth_header.keys())[0]
            auth_val = list(auth_header.values())[0][:20]

            print(f"\n{i}. Trying: {auth_type}: {auth_val}...")

            try:
                response = client.get(url, headers=headers)
                print(f"   Status: {response.status_code}")

                if response.status_code == 200:
                    data = response.json()
                    print("\n   ✅ SUCCESS! Auth format works!")
                    print(f"   Use header: {auth_type}")
                    print("-" * 60)

                    # Pretty print statuses
                    statuses = data.get("data") if isinstance(data, dict) else data
                    if isinstance(statuses, list):
                        for s in statuses:
                            if isinstance(s, dict):
                                sid = s.get("id", "?")
                                name = s.get("title") or s.get("name", s)
                                code = s.get("code", "")
                                print(f"   ID: {sid:3} | Code: {code:20} | Name: {name}")
                    else:
                        print(json.dumps(data, indent=2, ensure_ascii=False)[:500])
                    print("-" * 60)
                    return  # Found working auth!
                elif response.status_code == 401:
                    print("   ❌ Unauthorized")
                else:
                    print(f"   Error: {response.text[:100]}")

            except Exception as e:
                print(f"   Error: {e}")

        # Also try with query param
        print("\n7. Trying: ?api_key=...")
        try:
            response = client.get(f"{url}?api_key={API_KEY}", headers=base_headers)
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                print("   ✅ SUCCESS with query param!")
                print(response.json())
        except Exception as e:
            print(f"   Error: {e}")

    print("\n" + "=" * 60)
    print("All auth formats failed. Check API key or docs.")


if __name__ == "__main__":
    test_connection()
