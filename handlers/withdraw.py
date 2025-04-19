from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from loguru import logger
from services.solana_service import SolanaService
from services.jupiter_service import JupiterService
from solana.publickey import PublicKey
import asyncio
import time
from datetime import datetime
from services.firebase_service import FirebaseService
from config import SOLANA_TOKEN_ADDRESSES
from utils import log_transaction, validate_slippage

router = Router()
solana_service = SolanaService()
jupiter_service = JupiterService()

# Определение состояний FSM для процесса вывода средств
class WithdrawStates(StatesGroup):
    waiting_for_token = State()        # Ожидание выбора токена
    waiting_for_address = State()      # Ожидание ввода адреса получателя
    waiting_for_amount = State()       # Ожидание ввода суммы для вывода
    confirming_withdrawal = State()    # Подтверждение вывода

# Кэш для хранения цен токенов (чтобы не запрашивать их слишком часто)
token_prices_cache = {}
last_price_update = 0
CACHE_DURATION = 300  # 5 минут

async def get_token_prices():
    """Получение текущих цен токенов через Jupiter API"""
    global token_prices_cache, last_price_update
    
    # Проверяем, нужно ли обновить кэш
    current_time = time.time()
    if current_time - last_price_update > CACHE_DURATION or not token_prices_cache:
        try:
            # TODO: Здесь должен быть запрос к Jupiter API для получения цен
            # Для этого примера, используем заглушку с фиксированными ценами
            token_prices_cache = {
                'SOL': 124.46,
                'BONK': 0.00001263,
                'RAY': 1.839,
                'USDC': 1.0,
                'USDT': 1.0
            }
            last_price_update = current_time
            logger.info("Цены токенов обновлены")
        except Exception as e:
            logger.error(f"Ошибка при получении цен токенов: {e}")
            # Если не удалось получить цены, используем последние известные
            if not token_prices_cache:
                token_prices_cache = {
                    'SOL': 124.46,
                    'BONK': 0.00001263,
                    'RAY': 1.839,
                    'USDC': 1.0,
                    'USDT': 1.0
                }
    
    return token_prices_cache

async def get_user_wallet(user_id):
    """Получение кошелька пользователя из Firebase"""
    logger.info(f"[get_user_wallet] Запрос кошелька для user_id: {user_id}")
    try:
        wallet = await solana_service.wallet_service.get_wallet(user_id)
        if not wallet:
            logger.warning(f"[get_user_wallet] Кошелек не найден для user_id: {user_id}")
            return None, None
        logger.info(f"[get_user_wallet] Кошелек найден для user_id: {user_id}, public_key: {wallet['public_key']}")
        return wallet['public_key'], wallet['private_key']
    except Exception as e:
        logger.error(f"Ошибка при получении кошелька: {e}")
        return None, None

def create_token_keyboard(balances):
    """Создание клавиатуры с токенами для вывода"""
    keyboard = []
    
    # Добавляем кнопки с токенами
    token_buttons = []
    for token, balance in balances.items():
        if balance > 0:  # Показываем только токены с ненулевым балансом
            token_buttons.append(InlineKeyboardButton(
                text=f"{token}",
                callback_data=f"withdraw_token:{token}"
            ))
    
    # Разбиваем кнопки токенов по 3 в ряд
    for i in range(0, len(token_buttons), 3):
        keyboard.append(token_buttons[i:i+3])
    
    # Добавляем навигационные кнопки
    keyboard.append([
        InlineKeyboardButton(text="← Назад", callback_data="withdraw_back"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="withdraw_refresh")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def cmd_withdraw_with_user_id(message: types.Message, state: FSMContext, user_id: int):
    logger.info(f"[cmd_withdraw_with_user_id] Запуск вывода для user_id: {user_id}")
    try:
        user_pubkey, _ = await get_user_wallet(user_id)
        if not user_pubkey:
            await message.answer(
                "❌ У вас еще нет кошелька. Используйте команду /start для его создания."
            )
            return
        balances = await solana_service.get_all_balances(user_pubkey)
        if not balances:
            await message.answer(
                "❌ На вашем кошельке нет токенов для вывода."
            )
            return
        token_prices = await get_token_prices()
        text = "Выберите токен для вывода (Solana) 1/1\n\n"
        for token, balance in balances.items():
            price = token_prices.get(token, 0)
            usd_value = balance * price
            text += f"{token} — ${usd_value:.2f} — Цена: ${price}\n"
        keyboard = create_token_keyboard(balances)
        await message.answer(text, reply_markup=keyboard)
        await state.set_state(WithdrawStates.waiting_for_token)
        await state.update_data(balances=balances)
    except Exception as e:
        logger.error(f"Error in withdraw command for user {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при выводе средств. Попробуйте позже.")

@router.message(Command("withdraw"))
async def cmd_withdraw(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await cmd_withdraw_with_user_id(message, state, user_id)

@router.callback_query(F.data.startswith("withdraw_token:"), WithdrawStates.waiting_for_token)
async def process_token_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора токена для вывода"""
    user_id = callback.from_user.id
    token = callback.data.split(":", 1)[1]
    
    try:
        # Получаем балансы из состояния
        data = await state.get_data()
        balances = data.get("balances", {})
        
        # Проверяем, что выбранный токен есть в балансах
        if token not in balances:
            await callback.answer("❌ Токен не найден в вашем кошельке.", show_alert=True)
            return
        
        # Сохраняем выбранный токен в состоянии
        await state.update_data(selected_token=token, token_balance=balances[token])
        
        # Отвечаем на callback
        await callback.answer()
        
        # Запрашиваем адрес получателя
        await callback.message.edit_text(
            f"Выбран токен: {token}\n"
            f"Баланс: {balances[token]} {token}\n\n"
            f"Введите адрес кошелька Solana для вывода средств:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Назад", callback_data="withdraw_back_to_tokens")]
            ])
        )
        
        # Переходим к состоянию ожидания адреса
        await state.set_state(WithdrawStates.waiting_for_address)
        
    except Exception as e:
        logger.error(f"Error processing token selection for user {user_id}: {e}")
        await callback.message.edit_text("❌ Произошла ошибка при выборе токена. Попробуйте позже.")
        await state.clear()

@router.callback_query(F.data == "withdraw_back_to_tokens")
async def back_to_tokens(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору токена"""
    try:
        # Получаем данные из состояния
        data = await state.get_data()
        balances = data.get("balances", {})
        
        # Получаем цены токенов
        token_prices = await get_token_prices()
        
        # Формируем сообщение с балансами и USD ценами
        text = "Выберите токен для вывода (Solana) 1/1\n\n"
        
        for token, balance in balances.items():
            price = token_prices.get(token, 0)
            usd_value = balance * price
            text += f"{token} — ${usd_value:.2f} — Цена: ${price}\n"
        
        # Создаем клавиатуру с токенами
        keyboard = create_token_keyboard(balances)
        
        # Обновляем сообщение
        await callback.message.edit_text(text, reply_markup=keyboard)
        
        # Возвращаемся к состоянию выбора токена
        await state.set_state(WithdrawStates.waiting_for_token)
        
    except Exception as e:
        logger.error(f"Error returning to token selection: {e}")
        await callback.message.edit_text("❌ Произошла ошибка. Попробуйте заново с команды /withdraw")
        await state.clear()

@router.callback_query(F.data == "withdraw_refresh")
async def refresh_balances(callback: CallbackQuery, state: FSMContext):
    """Обновление балансов токенов"""
    user_id = callback.from_user.id
    
    try:
        # Получаем адрес кошелька пользователя
        user_pubkey, _ = await get_user_wallet(user_id)
        
        if not user_pubkey:
            await callback.answer("❌ Не удалось получить данные кошелька.", show_alert=True)
            return
        
        # Обновляем балансы токенов
        balances = await solana_service.get_all_balances(user_pubkey)
        
        # Обновляем цены токенов (сбрасываем кэш)
        global last_price_update
        last_price_update = 0
        token_prices = await get_token_prices()
        
        # Формируем обновленное сообщение
        text = "Выберите токен для вывода (Solana) 1/1\n\n"
        
        for token, balance in balances.items():
            price = token_prices.get(token, 0)
            usd_value = balance * price
            text += f"{token} — ${usd_value:.2f} — Цена: ${price}\n"
        
        # Создаем клавиатуру с токенами
        keyboard = create_token_keyboard(balances)
        
        # Обновляем сообщение
        await callback.message.edit_text(text, reply_markup=keyboard)
        
        # Сохраняем обновленные балансы в состоянии
        await state.update_data(balances=balances)
        
        # Отвечаем на callback
        await callback.answer("✅ Балансы обновлены")
        
    except Exception as e:
        logger.error(f"Error refreshing balances for user {user_id}: {e}")
        await callback.answer("❌ Ошибка при обновлении балансов", show_alert=True)

@router.message(WithdrawStates.waiting_for_address)
async def process_address(message: types.Message, state: FSMContext):
    """Обработка ввода адреса получателя"""
    user_id = message.from_user.id
    address = message.text.strip()
    
    try:
        # Проверяем формат адреса Solana
        try:
            PublicKey(address)
            valid_address = True
        except:
            valid_address = False
        
        if not valid_address:
            await message.answer(
                "❌ Некорректный адрес Solana. Пожалуйста, введите действительный адрес."
            )
            return
        
        # Получаем данные из состояния
        data = await state.get_data()
        token = data.get("selected_token")
        balance = data.get("token_balance", 0)
        
        # Сохраняем адрес в состоянии
        await state.update_data(recipient_address=address)
        
        # Запрашиваем сумму для вывода
        await message.answer(
            f"Адрес получателя: `{address}`\n\n"
            f"Введите сумму {token} для вывода (максимум {balance}):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Назад", callback_data="withdraw_back_to_tokens")]
            ])
        )
        
        # Переходим к состоянию ожидания суммы
        await state.set_state(WithdrawStates.waiting_for_amount)
        
    except Exception as e:
        logger.error(f"Error processing address for user {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при обработке адреса. Попробуйте позже.")
        await state.clear()

@router.message(WithdrawStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    """Обработка ввода суммы для вывода"""
    user_id = message.from_user.id
    amount_text = message.text.strip()
    
    try:
        # Парсим сумму
        try:
            amount = float(amount_text)
        except:
            await message.answer("❌ Некорректный формат суммы. Введите число.")
            return
        
        # Получаем данные из состояния
        data = await state.get_data()
        token = data.get("selected_token")
        balance = data.get("token_balance", 0)
        recipient_address = data.get("recipient_address")
        
        # Проверяем, достаточно ли средств
        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше нуля.")
            return
        
        if amount > balance:
            await message.answer(f"❌ Недостаточно средств. Максимальная сумма для вывода: {balance} {token}")
            return
        
        # Сохраняем сумму в состоянии
        await state.update_data(amount=amount)
        
        # Запрашиваем подтверждение вывода
        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data="withdraw_confirm"),
                InlineKeyboardButton(text="❌ Отменить", callback_data="withdraw_cancel")
            ]
        ])
        
        await message.answer(
            f"📤 Подтвердите вывод средств:\n\n"
            f"Токен: {token}\n"
            f"Сумма: {amount} {token}\n"
            f"Адрес получателя: `{recipient_address}`\n\n"
            f"Пожалуйста, проверьте данные и подтвердите вывод.",
            parse_mode="Markdown",
            reply_markup=confirm_keyboard
        )
        
        # Переходим к состоянию подтверждения вывода
        await state.set_state(WithdrawStates.confirming_withdrawal)
        
    except Exception as e:
        logger.error(f"Error processing amount for user {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при обработке суммы. Попробуйте позже.")
        await state.clear()

@router.callback_query(F.data.startswith("withdraw_confirm"))
async def confirm_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Обработка подтверждения вывода средств"""
    user_id = callback.from_user.id
    
    try:
        # Отвечаем на callback
        await callback.answer()
        
        # Показываем сообщение о процессе
        await callback.message.edit_text(
            "⏳ Выполняется операция вывода средств...\n"
            "Пожалуйста, подождите."
        )
        
        # Получаем данные из состояния
        data = await state.get_data()
        token = data.get("selected_token")
        amount = data.get("amount")
        recipient_address = data.get("recipient_address")
        
        if not all([token, amount, recipient_address]):
            raise ValueError("Недостаточно данных для вывода средств")
        
        # Получаем ключи пользователя
        user_pubkey, user_privkey = await get_user_wallet(user_id)
        
        # Выполняем перевод в зависимости от типа токена
        if token == "SOL":
            tx_signature = await solana_service.send_sol(
                from_private_key=user_privkey,
                to_address=recipient_address,
                amount=amount
            )
        else:
            token_address = SOLANA_TOKEN_ADDRESSES.get(token)
            if not token_address:
                raise ValueError(f"Неизвестный токен: {token}")
                
            # Явно приводим amount к float и убеждаемся, что адрес токена строка
            tx_signature = await solana_service.send_spl_token(
                from_private_key=user_privkey,
                to_address=str(recipient_address),
                token_mint=str(token_address),
                amount=float(amount)
            )
        
        # Формируем URL транзакции
        tx_url = f"https://solscan.io/tx/{tx_signature}"
        
        # Логируем успешную транзакцию
        log_transaction(
            user_id=user_id,
            tx_type="withdraw",
            token=token,
            amount=amount,
            status="success",
            tx_signature=tx_signature
        )
        
        # Отправляем сообщение об успехе
        await callback.message.edit_text(
            f"✅ Вывод средств выполнен успешно!\n"
            f"Токен: {token}\n"
            f"Сумма: {amount}\n"
            f"Получатель: {recipient_address}\n"
            f"Транзакция: {tx_url}"
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in withdrawal confirmation for user {user_id}: {error_msg}")
        
        # Логируем ошибку транзакции
        log_transaction(
            user_id=user_id,
            tx_type="withdraw",
            token=token if 'token' in locals() else 'unknown',
            amount=amount if 'amount' in locals() else 0,
            status="error",
            error=error_msg
        )
        
        # Отправляем сообщение об ошибке
        await callback.message.edit_text(
            f"❌ Ошибка при выводе средств: {error_msg}"
        )
    finally:
        # Очищаем состояние
        await state.clear()

@router.callback_query(F.data == "withdraw_cancel")
async def cancel_withdrawal(callback: CallbackQuery, state: FSMContext):
    """Отмена вывода средств"""
    await callback.answer()
    await callback.message.edit_text("❌ Операция вывода средств отменена.")
    await state.clear()

@router.callback_query(F.data == "withdraw_back")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await callback.answer()
    await callback.message.edit_text("Операция вывода средств отменена.")
    await state.clear() 