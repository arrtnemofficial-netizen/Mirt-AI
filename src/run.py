import os
import sys
import asyncio

import uvicorn


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Get port from environment variable, default to 8000
    # This bypasses shell expansion issues completely
    port = int(os.environ.get("PORT", 8000))

    print(f"Starting server on port {port}...")

    uvicorn.run(
        "src.server.main:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
