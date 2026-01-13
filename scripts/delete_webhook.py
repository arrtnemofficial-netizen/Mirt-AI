import asyncio

from aiogram import Bot

from src.conf.config import settings


async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN.get_secret_value())
    await bot.delete_webhook(drop_pending_updates=True)
    print("Webhook deleted successfully")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
