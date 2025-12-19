import asyncio
import logging
import sys


# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.append(".")

from langchain_core.messages import HumanMessage

from src.agents import get_active_graph
from src.services.supabase_store import create_supabase_store


async def main():
    print("--- STARTING REPRO ---")

    # 1. Initialize Store
    store = create_supabase_store()
    if not store:
        print("ERROR: Could not create Supabase store. Check env vars.")
        return

    print("Supabase Store created.")

    # 2. Get Graph
    graph = get_active_graph()

    # 3. Simulate User Message with Image
    # Using a known product image URL (e.g. from catalog or generic)
    # Or just a placeholder if we want to test the flow
    image_url = "https://mirt.ua/uploads/product/2023/11/16/65563a6b0b0a8_1.jpg"  # Example URL

    session_id = "test_repro_session_1"

    initial_state = {
        "messages": [
            HumanMessage(content="Що це за костюм?", additional_kwargs={"image_url": image_url})
        ],
        "metadata": {"session_id": session_id, "image_url": image_url, "has_image": True},
        "current_state": "STATE_0_INIT",
    }

    print(f"Invoking graph for session {session_id}...")

    # 4. Run Graph
    config = {"configurable": {"thread_id": session_id}}

    # We need to manually save initial state if we are bypassing the bot handler
    # But graph.invoke should handle it if we pass the state

    try:
        result = await graph.ainvoke(initial_state, config=config)

        print("\n--- RESULT ---")
        print(f"Current State: {result.get('current_state')}")
        print(f"Escalation: {result.get('metadata', {}).get('escalation_level')}")

        messages = result.get("messages", [])
        for m in messages:
            if hasattr(m, "content"):
                print(f"[{m.type}]: {m.content}")
            else:
                print(f"[dict]: {m.get('content')}")

    except Exception:
        logger.exception("Graph invocation failed")


if __name__ == "__main__":
    asyncio.run(main())
