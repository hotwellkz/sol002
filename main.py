import asyncio
import signal
import sys
import platform
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger
import firebase_admin
from firebase_admin import credentials, initialize_app
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold
from dotenv import load_dotenv
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties

from config import (
    TELEGRAM_BOT_TOKEN,
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_CONFIG,
    LOG_FILE
)
from handlers import start
# Импортируем объединенный маршрутизатор из handlers
from handlers import router as handlers_router

# Настройка логирования
logger.remove()  # Удаляем стандартный обработчик
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(
    LOG_FILE,
    rotation="1 day",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)

# Загрузка переменных окружения
load_dotenv()

# Инициализация Firebase
def init_firebase():
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            initialize_app(cred, FIREBASE_CONFIG)
            logger.info("Firebase initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        sys.exit(1)

# Инициализация бота и диспетчера
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Создаем диспетчер с настройками
dp = Dispatcher(
    storage=MemoryStorage(),
    # Разрешаем обработку всех типов обновлений
    handle_signals=True,
    ignore_network_errors=True,
)

# Регистрация маршрутизаторов
dp.include_router(handlers_router)  # Включает все обработчики из handlers/__init__.py

# Настройка команд бота
async def setup_commands(bot: Bot):
    """Настройка команд бота"""
    logger.info("Настройка команд бота...")
    try:
        # Удаление всех текущих команд
        await bot.delete_my_commands()
        
        # Установка всех команд бота
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="buy", description="Купить токены"),
            BotCommand(command="sell", description="Продать токены"),
            BotCommand(command="withdraw", description="Вывести средства"),
            BotCommand(command="export_keys", description="Экспортировать ключи"),
            BotCommand(command="balance", description="Показать баланс")
        ])
        logger.info("Команды бота успешно настроены")
    except Exception as e:
        logger.error(f"Ошибка при настройке команд бота: {e}")

# Обработчик graceful shutdown
async def shutdown(loop):
    logger.info("Shutting down...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.info(f"Cancelling {len(tasks)} outstanding tasks...")
    await asyncio.gather(*tasks, return_exceptions=True)
    await bot.session.close()
    loop.stop()
    logger.info("Shutdown complete.")

def check_solana_connection():
    """Проверка подключения к Solana RPC"""
    try:
        from solana.rpc.api import Client
        from config import SOLANA_RPC_URL

        client = Client(SOLANA_RPC_URL)
        # Проверяем подключение через getSlot
        slot = client.get_slot()
        if slot.value:
            logger.info(f"Successfully connected to Solana RPC. Current slot: {slot.value}")
            return True
        else:
            logger.error("Failed to connect to Solana RPC: Could not get current slot")
            return False
    except Exception as e:
        logger.error(f"Error connecting to Solana RPC: {e}")
        return False

async def main():
    """Запуск бота"""
    try:
        logger.info("Starting bot...")
        
        # Инициализация Firebase
        init_firebase()
        
        # Проверка подключения к Solana
        if not check_solana_connection():
            logger.error("Failed to connect to Solana RPC. Exiting...")
            return
        
        # Настройка команд бота
        await setup_commands(bot)
        
        logger.info("Bot is ready to accept messages")
        
        # Запуск бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == "__main__":
    try:
        logger.info("Starting application...")
        if platform.system() == 'Windows':
            # Для Windows используем простой запуск
            asyncio.run(main())
        else:
            # Для Unix систем используем более сложную настройку с обработкой сигналов
            loop = asyncio.get_event_loop()
            
            # Добавляем обработчики сигналов
            for signal_name in ('SIGINT', 'SIGTERM'):
                loop.add_signal_handler(
                    getattr(signal, signal_name),
                    lambda: asyncio.create_task(shutdown(loop))
                )
            
            try:
                loop.run_until_complete(main())
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down...")
                loop.run_until_complete(shutdown(loop))
            finally:
                loop.close()
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise