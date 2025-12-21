"""Aiogram-based Telegram bot that wraps the LangGraph app.



Features:

- Text and photo message handling

- Quick Reply keyboard based on conversation state

- Product photo sending

- Centralized error handling

"""



from __future__ import annotations



import asyncio

import contextlib

import logging

from typing import TYPE_CHECKING



from aiogram import Bot, Dispatcher, F

from aiogram.filters import CommandStart

from aiogram.types import (

    KeyboardButton,

    Message,

    ReplyKeyboardMarkup,

    ReplyKeyboardRemove,

)



from src.agents import get_active_graph  # Fixed: was graph_v2

from src.conf.config import settings
from src.core.prompt_registry import load_yaml_from_registry
from src.core.registry_keys import SystemKeys
from src.core.state_machine import EscalationLevel, State, get_keyboard_for_state, normalize_state

from src.services.conversation import ConversationHandler, create_conversation_handler

from src.services.infra.debouncer import BufferedMessage, MessageDebouncer

from src.services.infra.message_store import MessageStore, create_message_store

from src.services.infra.renderer import render_agent_response_text

from src.services.infra.session_store import InMemorySessionStore, SessionStore





if TYPE_CHECKING:

    from src.core.models import AgentResponse





logger = logging.getLogger(__name__)

def _get_currency() -> str:
    data = load_yaml_from_registry(SystemKeys.TEXTS.value)
    if isinstance(data, dict):
        return data.get("ui", {}).get("currency_uah", "UAH")
    return "UAH"






# ---------------------------------------------------------------------------

# Quick Reply Keyboards \u043f\u043e \u0441\u0442\u0430\u043d\u0430\u0445 (\u0432\u0438\u043a\u043e\u0440\u0438\u0441\u0442\u043e\u0432\u0443\u0454 state_machine)

# ---------------------------------------------------------------------------





def build_keyboard(

    current_state: str, escalation_level: str = "NONE"

) -> ReplyKeyboardMarkup | None:

    """Build Reply Keyboard based on conversation state using centralized state_machine."""



    # Normalize state and escalation

    state = normalize_state(current_state)

    esc_level = EscalationLevel.NONE

    with contextlib.suppress(ValueError):

        esc_level = EscalationLevel(escalation_level.upper())



    platform_kb = get_keyboard_for_state(state, esc_level)

    if not platform_kb:

        # If END state, remove keyboard explicitly

        if state == State.STATE_7_END:

            return ReplyKeyboardRemove()

        return None



    # Convert generic PlatformKeyboard to aiogram ReplyKeyboardMarkup

    buttons = [

        [KeyboardButton(text=btn_text) for btn_text in row] for row in platform_kb.buttons

    ]



    return ReplyKeyboardMarkup(

        keyboard=buttons,

        resize_keyboard=True,

        one_time_keyboard=platform_kb.one_time,

    )





def build_dispatcher(

    store: SessionStore,

    message_store: MessageStore | None = None,

    runner=None,

) -> Dispatcher:

    """Create a Dispatcher with handlers bound to the shared store."""

    dp = Dispatcher()

    msg_store = message_store or create_message_store()



    active_runner = runner or get_active_graph()



    # Create centralized conversation handler

    conversation_handler = create_conversation_handler(

        session_store=store,

        message_store=msg_store,

        runner=active_runner,

    )



    @dp.message(CommandStart())
    async def handle_start(message: Message) -> None:
        """Soft reset for a fresh start or /start command."""

        from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header



        def _get_reply(header: str, default: str) -> str:

            s = get_snippet_by_header(header)

            return "".join(s) if s else default



        session_id = str(message.chat.id)

        thread_id = f"{session_id}:{uuid.uuid4()}"

        store.save(

            session_id,

            {

                "messages": [],

                "metadata": {

                    "session_id": session_id,

                    "thread_id": thread_id,

                    "vision_greeted": False,

                    "has_image": False,

                },

                "current_state": "STATE_0_INIT",

                "dialog_phase": "INIT",

                "should_escalate": False,

                "has_image": False,

                "detected_intent": None,

                "selected_products": [],

                "offered_products": [],

                "step_number": 0,

            },

        )

        await message.answer(_get_reply("BOT_START_REPLY", "\u041c\u043e\u0436\u0435\u043c\u043e \u043f\u043e\u0447\u0430\u0442\u0438 \u0441\u043f\u0456\u043b\u043a\u0443\u0432\u0430\u043d\u043d\u044f!"))



    @dp.message(Command("restart"))
    async def handle_restart(message: Message) -> None:
        """Hard reset: clear session state and history."""



        import uuid

        from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header



        def _get_reply(header: str, default: str) -> str:

            s = get_snippet_by_header(header)

            return "".join(s) if s else default



        session_id = str(message.chat.id)

        thread_id = f"{session_id}:{uuid.uuid4()}"



        store.save(

            session_id,

            {

                "messages": [],

                "metadata": {

                    "session_id": session_id,

                    "thread_id": thread_id,

                    "vision_greeted": False,

                    "has_image": False,

                },

                "current_state": "STATE_0_INIT",

                "dialog_phase": "INIT",

                "should_escalate": False,

                "has_image": False,

                "detected_intent": None,

                "selected_products": [],

                "offered_products": [],

                "step_number": 0,

            },

        )



        # 2) \u0412\u0438\u0434\u0430\u043b\u044f\u0454\u043c\u043e \u0456\u0441\u0442\u043e\u0440\u0456\u044e \u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u044c, \u044f\u043a\u0449\u043e \u0441\u0445\u043e\u0432\u0438\u0449\u0435 \u0446\u0435 \u043f\u0456\u0434\u0442\u0440\u0438\u043c\u0443\u0454

        try:

            delete_fn = getattr(msg_store, "delete", None)

            if callable(delete_fn):

                delete_fn(session_id)

        except Exception as e:

            logger.warning("Failed to delete message history for session %s: %s", session_id, e)



        await message.answer(

            _get_reply("BOT_RESTART_REPLY", "\u0421\u0435\u0441\u0456\u044e \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u0442\u0438\u043b\u0430. \u041d\u0430\u0434\u0456\u0448\u043b\u0456\u0442\u044c \u0444\u043e\u0442\u043e \u0430\u0431\u043e \u0437\u0430\u043f\u0438\u0442\u0430\u043d\u043d\u044f.")

        )



    @dp.message(F.text)

    async def handle_text(message: Message) -> None:

        await _process_incoming(message, conversation_handler)



    @dp.message(F.photo)

    async def handle_photo(message: Message) -> None:

        caption = message.caption or ""

        description = caption if caption else ""



        # Get photo URL from Telegram

        photo = message.photo[-1]  # Get largest photo

        file = await message.bot.get_file(photo.file_id)

        image_url = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN.get_secret_value()}/{file.file_path}"



        await _process_incoming(

            message,

            conversation_handler,

            override_text=description,

            has_image=True,

            image_url=image_url,

        )



    return dp





def build_bot() -> Bot:

    """Instantiate Bot from settings."""

    return Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())





async def _process_incoming(

    message: Message,

    handler: ConversationHandler,

    override_text: str | None = None,

    has_image: bool = False,

    image_url: str | None = None,

) -> None:

    """Process incoming Telegram message using ConversationHandler."""

    text = override_text or message.text or ""

    session_id = str(message.chat.id)



    # Build extra metadata for photos

    extra_metadata = None

    if has_image:

        extra_metadata = {

            "has_image": True,

            "image_url": image_url,

        }



    # Use centralized handler - all error handling is done internally

    result = await handler.process_message(session_id, text, extra_metadata=extra_metadata)



    if result.is_fallback:

        logger.warning(

            "Fallback response for session %s: %s",

            session_id,

            result.error,

        )



    await _dispatch_to_telegram(message, result.response)





async def _dispatch_to_telegram(message: Message, agent_response: AgentResponse) -> None:

    """Send formatted agent response back to the chat with keyboard."""



    # Build keyboard based on state

    keyboard = build_keyboard(

        current_state=agent_response.metadata.current_state,

        escalation_level=agent_response.metadata.escalation_level,

    )



    text_chunks = render_agent_response_text(agent_response)



    # Send text messages (last one with keyboard)

    for i, chunk in enumerate(text_chunks):

        if not chunk or not chunk.strip():

            continue



    # Send product photos only for vision/photo-ident responses to avoid \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0438\u0445 \u0444\u043e\u0442\u043e

    if agent_response.metadata.intent == "PHOTO_IDENT":

        for _i, product in enumerate(agent_response.products):

            if product.photo_url:

                await message.answer_photo(

                    photo=product.photo_url,

                    caption="",  # \u0431\u0435\u0437 \u0434\u0443\u0431\u043b\u044e\u0432\u0430\u043d\u043d\u044f \u0442\u0435\u043a\u0441\u0442\u0443/\u0446\u0456\u043d\u0438

                )





async def run_polling(store: SessionStore | None = None) -> None:

    """Convenience entry point for local polling runs."""

    # Configure logging to show INFO level for our modules

    logging.basicConfig(

        level=logging.INFO,

        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",

        datefmt="%H:%M:%S",

    )

    # Reduce noise from external libs

    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.getLogger("aiogram").setLevel(logging.WARNING)

    logging.getLogger("httpcore").setLevel(logging.WARNING)



    print("🚀 Starting Telegram bot with INFO logging enabled...")



    from src.services.infra.supabase_store import create_supabase_store



    # Try to use Supabase store if not provided

    if store is None:

        store = create_supabase_store()



    if store is None:

        print(

            "⚠️ Using InMemorySessionStore - session state will be lost on restart!\n"

            "   Set SUPABASE_URL and SUPABASE_API_KEY for persistent session storage."

        )



    # Send product photos (last one with keyboard)

    for i, product in enumerate(agent_response.products):

        if product.photo_url:

            is_last = i == len(agent_response.products) - 1

            await message.answer_photo(

                photo=product.photo_url,

                caption=f"{product.name} - {product.price} \u0433\u0440\u043d",

                reply_markup=keyboard if is_last else None,

            )





def run_polling(store: SessionStore | None = None) -> None:

    """Convenience entry point for local polling runs."""



    session_store = store or InMemorySessionStore()

    message_store = create_message_store()

    bot = build_bot()

    dp = build_dispatcher(session_store, message_store)

    asyncio.run(dp.start_polling(bot))





if __name__ == "__main__":

    run_polling()

