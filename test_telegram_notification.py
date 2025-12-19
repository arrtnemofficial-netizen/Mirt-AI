#!/usr/bin/env python
"""
Quick test for Telegram manager notifications.
Run: python test_telegram_notification.py
"""

import asyncio
import sys
from pathlib import Path


# Add project root
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))


async def main():
    print("\n" + "=" * 60)
    print("📲 TELEGRAM NOTIFICATION TEST")
    print("=" * 60)

    from src.conf.config import settings
    from src.services.notification_service import NotificationService

    # Check config
    bot_token = settings.MANAGER_BOT_TOKEN.get_secret_value()
    chat_id = settings.MANAGER_CHAT_ID

    if not bot_token:
        print("\n❌ MANAGER_BOT_TOKEN not configured!")
        print("   Add to .env or Railway:")
        print("   MANAGER_BOT_TOKEN=7123456789:AAHxxxxx...")
        return

    if not chat_id:
        print("\n❌ MANAGER_CHAT_ID not configured!")
        print("   Add to .env or Railway:")
        print("   MANAGER_CHAT_ID=123456789")
        return

    print(f"\n✅ Bot token: {bot_token[:20]}...")
    print(f"✅ Chat ID: {chat_id}")

    # Send test notification
    print("\n📤 Sending test notification...")

    notification = NotificationService()
    success = await notification.send_escalation_alert(
        session_id="TEST_123456",
        reason="🧪 ТЕСТ: Товар не знайдено в каталозі",
        user_context="Користувач надіслав фото товару з іншого магазину",
        details={
            "dialog_phase": "ESCALATED",
            "current_state": "STATE_0_INIT",
            "intent": "PHOTO_IDENT",
            "claimed_product": "Невідомий товар",
            "confidence": 35,
        },
    )

    if success:
        print("\n✅ УСПІШНО! Перевірте Telegram - повідомлення має прийти!")
        print("=" * 60)
    else:
        print("\n❌ Помилка відправки. Перевірте:")
        print("   1. Правильність токена бота")
        print("   2. Правильність Chat ID")
        print("   3. Чи написали ви /start боту")
        print("=" * 60)


if __name__ == "__main__":
    # Windows event loop fix
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
