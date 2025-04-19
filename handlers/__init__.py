from aiogram import Router
from handlers import start, buy, sell, withdraw, export_keys, balance
from keyboards import inline

router = Router()

# Регистрируем все хэндлеры
router.include_router(start.router)
router.include_router(buy.router)
router.include_router(sell.router)
router.include_router(withdraw.router)
router.include_router(export_keys.router)
router.include_router(balance.router)
router.include_router(inline.router)  # Добавляем роутер для обработки callback-кнопок