
import os
from dotenv import load_dotenv
import httpx

load_dotenv()

url = os.getenv("SNITKIX_API_URL", "https://crm.sitniks.com")
key = os.getenv("SNITKIX_API_KEY", "")

print(f"URL: {url}")
print(f"Key loaded: {'Yes' if key else 'No'}")
if key:
    print(f"Key prefix: {key[:4]}...{key[-4:]}")

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

with httpx.Client() as client:
    try:
        resp = client.get(f"{url}/open-api/products", headers=headers, params={"limit": 1})
        print(f"Status Code: {resp.status_code}")
        if resp.status_code == 200:
            print("Success!")
            print(resp.json().get("data", [])[0].get("title", "No title"))
        else:
            print(f"Error: {resp.status_code}")
            print(resp.text[:200])
    except Exception as e:
        print(f"Exception: {e}")
