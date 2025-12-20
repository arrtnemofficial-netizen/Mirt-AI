#!/usr/bin/env python3
"""Test Sitniks CRM API connection and fetch order statuses."""

import json
import os
import sys

import httpx
import pytest
from dotenv import load_dotenv


# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv()

API_KEY = os.getenv("SNITKIX_API_KEY", "")
API_URLS = [
    os.getenv("SNITKIX_API_URL", "").strip(),
    "https://crm.sitniks.com",
    "https://api.sitniks.com",
    "https://api.sitniks.ua",
    "https://web.sitniks.com",
]
API_URLS = [url for url in API_URLS if url]


def test_connection():
    """Test Sitniks API and get order statuses."""
    if not API_KEY:
        pytest.fail("SNITKIX_API_KEY is not set. Configure real API key in .env.")

    print("Testing Sitniks API...")
    print(f"Key: {API_KEY[:10]}..." if API_KEY else "Key: NOT SET")
    print("=" * 60)

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
        for api_url in API_URLS:
            print(f"\nURL: {api_url}")
            url = f"{api_url}/open-api/orders/statuses"

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
                        print("\n   OK. Auth format works!")
                        print(f"   Use header: {auth_type}")
                        print("-" * 60)

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
                        return
                    if response.status_code == 401:
                        print("   Unauthorized")
                    else:
                        print(f"   Error: {response.text[:100]}")

                except Exception as e:
                    print(f"   Error: {e}")

            print("\n7. Trying: ?api_key=...")
            try:
                response = client.get(f"{url}?api_key={API_KEY}", headers=base_headers)
                print(f"   Status: {response.status_code}")
                if response.status_code == 200:
                    print("   OK. SUCCESS with query param!")
                    print(response.json())
                    return
            except Exception as e:
                print(f"   Error: {e}")

    pytest.fail("All auth formats failed. Check API key or API URL.")


if __name__ == "__main__":
    test_connection()
