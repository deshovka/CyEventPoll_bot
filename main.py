import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from configparser import ConfigParser
from handlers import router
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def load_config():
    config = ConfigParser()
    config.read("config.ini")
    return config

def create_bot():
    config = load_config()
    token = config["Bot"]["token"]
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))

def create_dispatcher():
    dp = Dispatcher()
    dp.include_router(router)
    return dp

async def main():
    await init_db()
    dp = create_dispatcher()
    bot = create_bot()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())