#!/usr/bin/env python3
"""Test Sitniks CRM API - try all combinations of URLs and keys."""

import httpx
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent / ".env")


# All possible API keys
API_KEYS = []
primary_key = os.getenv("SNITKIX_API_KEY", "").strip()
alt_key = os.getenv("SNITKIX_API_KEY_ALT", "").strip()
if primary_key:
    API_KEYS.append(("primary", primary_key))
if alt_key:
    API_KEYS.append(("alt", alt_key))
if not API_KEYS:
    pytest.fail("SNITKIX_API_KEY is not set. Configure real API key in .env.")

# All possible API URLs
env_urls = [
    url.strip()
    for url in os.getenv("SNITKIX_API_URLS", "").split(",")
    if url.strip()
]
if not env_urls:
    env_url = os.getenv("SNITKIX_API_URL", "").strip()
    if env_url:
        env_urls = [env_url]
API_URLS = env_urls or [
    "https://crm.sitniks.com",
    "https://api.sitniks.com",
    "https://api.sitniks.ua",
    "https://web.sitniks.com",
    "https://web.sitniks.com/api",
]

# Endpoints to try
ENDPOINTS = [
    "/open-api/orders/statuses",
    "/api/orders/statuses",
    "/v1/orders/statuses",
]


def test_all_combinations():
    """Try all combinations to find working one."""
    print("=" * 70)
    print("SITNIKS API BRUTE FORCE TEST")
    print("=" * 70)

    with httpx.Client(timeout=10) as client:
        for url in API_URLS:
            for endpoint in ENDPOINTS:
                full_url = f"{url}{endpoint}"

                for key_name, key in API_KEYS:
                    headers = {
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    }

                    try:
                        response = client.get(full_url, headers=headers)
                        status = response.status_code

                        if status == 200:
                            print("\n✅ SUCCESS!")
                            print(f"   URL: {full_url}")
                            print(f"   Key: {key_name}")
                            print(f"   Response: {response.text[:500]}")
                            return
                        elif status == 401:
                            print(f"❌ 401 {full_url} [{key_name[:10]}...]")
                        elif status == 403:
                            print(f"⚠️  403 {full_url} [{key_name[:10]}...]")
                        elif status == 404:
                            pass  # Skip 404s silently
                        else:
                            print(f"?  {status} {full_url}")

                    except httpx.ConnectError:
                        pass  # Skip connection errors
                    except Exception as e:
                        print(f"Error: {e}")

    print("\n" + "=" * 70)
    print("No working combination found.")
    print("\nPossible issues:")
    print("1. API access requires paid plan")
    print("2. API key not activated for this company")
    print("3. Different auth method needed (OAuth?)")
    print("=" * 70)


if __name__ == "__main__":
    test_all_combinations()
