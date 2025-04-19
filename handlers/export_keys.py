from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loguru import logger
from services.wallet import WalletService
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import asyncio

router = Router()
wallet_service = WalletService()

class ExportStates(StatesGroup):
    waiting_for_confirmation = State()

@router.message(Command("export_keys"))
async def cmd_export_keys(message: types.Message, state: FSMContext):
    """Обработчик команды /export_keys"""
    try:
        # Создаем клавиатуру для подтверждения
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_export"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_export")
                ]
            ]
        )
        
        # Отправляем предупреждение и запрашиваем подтверждение
        await message.answer(
            "⚠️ ВНИМАНИЕ! Важная информация о безопасности!\n\n"
            "Вы запросили экспорт приватного ключа вашего кошелька. "
            "Пожалуйста, помните:\n\n"
            "1. НИКОГДА не передавайте приватный ключ третьим лицам\n"
            "2. Храните ключ в надежном месте\n"
            "3. Любой, кто получит доступ к ключу, получит полный контроль над кошельком\n\n"
            "Вы уверены, что хотите продолжить?",
            reply_markup=keyboard
        )
        
        # Устанавливаем состояние ожидания подтверждения
        await state.set_state(ExportStates.waiting_for_confirmation)
        logger.info(f"User {message.from_user.id} initiated export keys command")
        
    except Exception as e:
        logger.error(f"Error in export keys command: {e}")
        await message.answer("Произошла ошибка при экспорте ключей. Попробуйте позже.")

@router.callback_query(F.data == "confirm_export", ExportStates.waiting_for_confirmation)
async def process_export_confirmation(callback: CallbackQuery, state: FSMContext):
    """Обработка подтверждения экспорта ключей"""
    try:
        user_id = callback.from_user.id
        
        # Получаем приватный ключ
        private_key = await wallet_service.export_private_key(user_id)
        
        if private_key:
            # Отправляем приватный ключ в монопропорциональном шрифте
            key_message = await callback.message.answer(
                "🔐 Ваш приватный ключ:\n\n"
                f"`{private_key}`\n\n"
                "⚠️ Сохраните его в надежном месте!\n"
                "❗️ Это сообщение будет автоматически удалено через 30 секунд",
                parse_mode="Markdown"
            )
            
            # Удаляем сообщение с кнопками подтверждения
            await callback.message.delete()
            
            # Отправляем предупреждение об автоудалении
            warning_message = await callback.message.answer(
                "⏳ У вас есть 30 секунд, чтобы сохранить ключ"
            )
            
            # Ждем 30 секунд и удаляем оба сообщения
            await asyncio.sleep(30)
            await key_message.delete()
            await warning_message.delete()
            
            # Отправляем финальное сообщение
            await callback.message.answer("✅ Сообщение с ключом удалено в целях безопасности")
            
            logger.info(f"Private key exported and auto-deleted for user {user_id}")
        else:
            await callback.message.answer(
                "❌ Не удалось получить приватный ключ. Возможно, у вас еще нет кошелька.\n"
                "Используйте команду /start для создания кошелька."
            )
    except Exception as e:
        logger.error(f"Error exporting private key for user {callback.from_user.id}: {e}")
        await callback.message.answer("Произошла ошибка при экспорте ключей. Попробуйте позже.")
    finally:
        # Очищаем состояние
        await state.clear()

@router.callback_query(F.data == "cancel_export", ExportStates.waiting_for_confirmation)
async def process_export_cancellation(callback: CallbackQuery, state: FSMContext):
    """Обработка отмены экспорта ключей"""
    try:
        # Удаляем сообщение с кнопками
        await callback.message.delete()
        
        # Отправляем сообщение об отмене
        await callback.message.answer("❌ Экспорт ключей отменен.")
        logger.info(f"Key export cancelled by user {callback.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error cancelling key export: {e}")
    finally:
        # Очищаем состояние
        await state.clear() 