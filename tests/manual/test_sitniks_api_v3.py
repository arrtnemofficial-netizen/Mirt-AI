#!/usr/bin/env python3
"""Test Sitniks CRM API - try with company ID and different headers."""

import httpx
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

COMPANY_ID = os.getenv("SNITKIX_COMPANY_ID", "").strip()
API_KEY_OPEN = os.getenv("SNITKIX_API_KEY", "").strip()
API_KEY_FIRST = os.getenv("SNITKIX_API_KEY_ALT", "").strip()

BASE_URL = os.getenv("SNITKIX_API_URL", "").strip() or "https://crm.sitniks.com"


def test():
    print("=" * 70)
    print("SITNIKS API - Testing with Company ID")
    print(f"Company ID: {COMPANY_ID}")
    print("=" * 70)

    if not COMPANY_ID:
        pytest.fail("SNITKIX_COMPANY_ID is not set. Configure real company ID in .env.")
    if not API_KEY_OPEN:
        pytest.fail("SNITKIX_API_KEY is not set. Configure real API key in .env.")

    with httpx.Client(timeout=15) as client:
        tests = [
            # Try different header combinations
            (
                "Bearer + X-Company-Id",
                {
                    "Authorization": f"Bearer {API_KEY_OPEN}",
                    "X-Company-Id": COMPANY_ID,
                },
            ),
            (
                "Bearer + Company-Id",
                {
                    "Authorization": f"Bearer {API_KEY_OPEN}",
                    "Company-Id": COMPANY_ID,
                },
            ),
            (
                "Bearer + x-company-id",
                {
                    "Authorization": f"Bearer {API_KEY_OPEN}",
                    "x-company-id": COMPANY_ID,
                },
            ),
            (
                "ApiKey header",
                {
                    "ApiKey": API_KEY_OPEN,
                },
            ),
            (
                "X-Api-Token",
                {
                    "X-Api-Token": API_KEY_OPEN,
                },
            ),
            (
                "Token header",
                {
                    "Token": API_KEY_OPEN,
                },
            ),
            (
                "Basic Auth (key as user)",
                {
                    "Authorization": f"Basic {API_KEY_OPEN}",
                },
            ),
        ]
        if API_KEY_FIRST:
            tests.append(
                (
                    "Alt key as Bearer",
                    {
                        "Authorization": f"Bearer {API_KEY_FIRST}",
                    },
                )
            )

        for name, headers in tests:
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
            )

            url = f"{BASE_URL}/open-api/orders/statuses"

            try:
                response = client.get(url, headers=headers)
                status = response.status_code

                if status == 200:
                    try:
                        data = response.json()
                        print(f"\n✅ SUCCESS with: {name}")
                        print(f"   Response: {data}")
                        return
                    except:
                        print(f"⚠️  200 but not JSON: {name}")
                elif status == 401:
                    print(f"❌ 401: {name}")
                elif status == 403:
                    print(f"⚠️  403: {name}")
                else:
                    print(f"?  {status}: {name}")

            except Exception as e:
                print(f"Error ({name}): {e}")

        # Try with query params
        print("\n--- Trying query params ---")
        params_tests = [
            ("api_key param", {"api_key": API_KEY_OPEN}),
            ("apiKey param", {"apiKey": API_KEY_OPEN}),
            ("token param", {"token": API_KEY_OPEN}),
            ("key param", {"key": API_KEY_OPEN}),
            ("companyId + api_key", {"companyId": COMPANY_ID, "api_key": API_KEY_OPEN}),
        ]

        for name, params in params_tests:
            try:
                response = client.get(
                    f"{BASE_URL}/open-api/orders/statuses",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if response.status_code == 200:
                    try:
                        data = response.json()
                        print(f"\n✅ SUCCESS with: {name}")
                        print(f"   Response: {data}")
                        return
                    except:
                        print(f"⚠️  200 but not JSON: {name}")
                else:
                    print(f"❌ {response.status_code}: {name}")
            except Exception as e:
                print(f"Error: {e}")

    print("\n" + "=" * 70)
    print("CONCLUSION: Standard Bearer auth doesn't work.")
    print("This likely means:")
    print("1. Free trial does NOT include API access")
    print("2. Need to contact Sitniks support to enable API")
    print("=" * 70)


if __name__ == "__main__":
    test()
