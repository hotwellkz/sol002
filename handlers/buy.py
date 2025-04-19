from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from loguru import logger
from services.jupiter_service import JupiterService
from services.firebase_service import FirebaseService
from config import SOLANA_RPC_URL, SOLANA_TOKEN_ADDRESSES
from utils import log_transaction

router = Router()
jupiter = JupiterService()
firebase = FirebaseService()

# Обработчик для команды отмены текущей операции
@router.message(F.text == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext):
    """Отменяет текущую операцию и сбрасывает состояние"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нет активной операции для отмены.")
        return
    
    await state.clear()
    await message.answer("✅ Текущая операция отменена.")

class BuyStates(StatesGroup):
    waiting_for_token = State()
    waiting_for_amount = State()

async def get_user_wallet(user_id: int) -> tuple[str, str]:
    """
    Получает публичный и приватный ключи пользователя из Firebase
    
    Args:
        user_id: Telegram ID пользователя
        
    Returns:
        tuple: (public_key, private_key)
        
    Raises:
        Exception: Если ключи не найдены
    """
    try:
        wallet_data = await firebase.get_user_wallet(user_id)
        if not wallet_data:
            raise Exception("Пользователь не найден в базе данных")
            
        public_key = wallet_data.get('public_key')
        private_key = wallet_data.get('private_key')
        
        if not public_key or not private_key:
            raise Exception("Ключи кошелька не найдены")
            
        return public_key, private_key
        
    except Exception as e:
        logger.error(f"Error getting user wallet: {str(e)}")
        raise

@router.message(Command("buy"))
async def cmd_buy(message: Message, state: FSMContext):
    current_state = await state.get_state()
    from loguru import logger
    logger.info(f"[cmd_buy] Текущее состояние до установки: {current_state}")
    await state.set_state(BuyStates.waiting_for_token)
    new_state = await state.get_state()
    logger.info(f"[cmd_buy] Состояние после установки: {new_state}")
    await message.answer("Введите символ токена или адрес для покупки")

@router.message(BuyStates.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    from loguru import logger
    current_state = await state.get_state()
    logger.info(f"[process_token] Вызван обработчик process_token. Текущее состояние: {current_state}, текст: '{message.text}'")
    token_input = message.text.strip()
    
    # Вывод для отладки
    logger.info(f"Получен ввод токена: {token_input}")
    
    # Проверка на команды
    if token_input.startswith('/'):
        logger.info(f"🔍 Обнаружена команда: {token_input}")
        command = token_input.split(' ')[0].lower()
        await state.clear()
        # Показываем 'Операция покупки отменена.' только для /cancel
        if command == '/cancel':
            await message.answer("Операция покупки отменена.")
        # Перенаправляем на соответствующую команду
        if command == '/balance':
            logger.info("🔍 Перенаправление на команду /balance")
            from handlers.balance import cmd_balance
            await cmd_balance(message, state)
        # Можно добавить аналогично для других команд, если нужно
        return
    
    # Проверка, если пользователь пытается купить SOL с помощью SOL
    if token_input.upper() == 'SOL' or token_input == 'So11111111111111111111111111111111111111112':
        logger.info("🔍 Пользователь пытается купить SOL используя SOL")
        await message.answer("❌ Вы не можете купить SOL используя SOL. Пожалуйста, выберите другой токен.")
        return
    
    # Определяем адрес токена с учетом регистра и синонимов
    normalized_input = token_input.replace(' ', '').upper()
    token_address = None
    for symbol, address in SOLANA_TOKEN_ADDRESSES.items():
        if normalized_input == symbol.replace(' ', '').upper():
            token_address = address
            logger.info(f"🔍 Найден адрес для символа {symbol}: {token_address}")
            break
    if not token_address:
        # Пытаемся найти частичное совпадение
        for symbol, address in SOLANA_TOKEN_ADDRESSES.items():
            if normalized_input in symbol.replace(' ', '').upper():
                token_address = address
                logger.info(f"🔍 Найдено частичное совпадение: символ {symbol}, адрес {address}")
                break
    if not token_address:
        token_address = token_input
        logger.info(f"🔍 Начальный адрес токена: {token_address}")
    # Если не найдено точное совпадение — продолжаем старую логику
    if token_address == token_input:
        # Пытаемся найти известный токен по его символу
        found = False
        for symbol, address in SOLANA_TOKEN_ADDRESSES.items():
            if token_input.upper() in symbol:
                token_address = address
                logger.info(f"🔍 Найдено частичное совпадение: символ {symbol}, адрес {address}")
                found = True
                break
        if not found:
            # Если не найдено среди известных — ищем через Jupiter API
            try:
                tokens_list = await jupiter.get_all_tokens()
            except Exception as e:
                logger.error(f"Ошибка при получении списка токенов Jupiter: {str(e)}")
                await message.answer("❌ Не удалось получить список токенов с Jupiter API. Попробуйте позже.")
                return
            # Более гибкий поиск по символу
            normalized_input = token_input.replace(' ', '').upper()
            matches = [
                t for t in tokens_list
                if isinstance(t, dict) and t.get('symbol', '').replace(' ', '').upper() == normalized_input
            ]
            if matches:
                token_data = matches[0]
                logger.info(f"Структура найденного токена: {token_data}")
                token_address = (
                    token_data.get('address') or
                    token_data.get('mintAddress') or
                    token_data.get('mint')
                )
                if not token_address:
                    logger.error(f"Токен найден, но не содержит address/mintAddress/mint: {token_data}")
                    await message.answer(f"❌ Токен найден через Jupiter, но не содержит адреса. Попробуйте ввести mint-адрес вручную.")
                    return
                logger.info(f"🔍 Найден токен через Jupiter API: {token_address}")
            # --- ВАЖНО ---
            # Если не найдено ни одного совпадения — НЕ делаем return, а просто используем введённый текст как адрес токена
            # и продолжаем выполнение, чтобы показать карточку токена
            # (ошибку показываем только если не проходит базовую валидацию)
        logger.info(f"🔍 Используем введенный текст как адрес токена: {token_address}")

    
    # Дополнительная проверка, что это не адрес SOL
    if token_address == 'So11111111111111111111111111111111111111112':
        logger.info("🔍 Обнаружен адрес SOL")
        await message.answer("❌ Вы не можете купить SOL используя SOL. Пожалуйста, выберите другой токен.")
        return
    
    import re
    # Валидация токена/адреса
    if not re.match(r'^[A-Za-z0-9]{3,44}$', token_input):
        await message.answer("❌ Введите корректный символ токена или адрес токена (без пробелов и спецсимволов, 3-44 символа).")
        return
    try:
        # Получаем баланс SOL пользователя (заглушка)
        user_sol_balance = 1.0
        
        logger.info(f"🔍 Пытаемся получить маршрут для токена: {token_address}")
        
        # Получаем маршрут для отображения информации
        try:
            # Получаем маршрут для 1 SOL
            route = await jupiter.get_best_route(
                input_mint="So11111111111111111111111111111111111111112",  # SOL
                output_mint=token_address,
                amount=1000000000,  # 1 SOL
                slippage=10.0
            )

            # --- Показываем карточку токена даже если нет маршрута ---
            route_exists = route and route.get('outAmount')
            try:
                decimals = await jupiter.get_token_decimals(token_address)
            except Exception:
                decimals = 6  # по умолчанию
            if route_exists:
                out_amount_raw = float(route.get('outAmount', 0))
                out_amount = out_amount_raw / (10 ** decimals)
                price_impact = float(route.get('priceImpactPct', 0))
                swap_usd_value = route.get('swapUsdValue')
                try:
                    swap_usd_value = float(swap_usd_value)
                except Exception:
                    swap_usd_value = None
            else:
                out_amount = 0.0
                price_impact = 0.0
                swap_usd_value = None
            market_name = route.get('marketName') if route_exists else token_input.upper()
            if not market_name or market_name.lower() == 'unknown':
                market_name = token_input.upper()
            token_info = f"Купить ${token_input.upper()} — ({market_name})\n"
            token_info += f"{token_address}\n\n"
            token_info += f"Баланс: {user_sol_balance} SOL\n"
            if route_exists:
                token_info += f"Price: {out_amount:.6f} {token_input.upper()} за 1 SOL\n"
            else:
                token_info += f"Price: недоступно\n"
            if swap_usd_value:
                token_info += f"Объем сделки: ${swap_usd_value:,.2f}\n"
            else:
                token_info += f"Объем сделки: недоступно\n"
            token_info += "LIQ: недоступно\n"
            token_info += "MC: недоступно\n"
            token_info += "Децентрализован ✅\n\n"
            if route_exists:
                token_info += f"1 SOL ⇄ {out_amount:.6f} {token_input.upper()}\n"
                token_info += f"Влияние на цену: {price_impact:.2f}%"
            else:
                token_info += f"1 SOL ⇄ ? {token_input.upper()}\n"
                token_info += f"Влияние на цену: недоступно"
            # Кнопки покупки (разрешаем попытку покупки)
            amounts_sol = [0.01, 0.1, 0.5, 1]
            token_buttons = []
            for sol_amt in amounts_sol:
                token_amt = out_amount * sol_amt if route_exists else 0.0
                token_amt_str = f"{token_amt:.6f}".rstrip('0').rstrip('.') if route_exists else f"?"
                token_buttons.append(
                    InlineKeyboardButton(
                        text=f"Купить {token_amt_str} {token_input.upper()}",
                        callback_data=f"buy_{sol_amt}_{token_address}"
                    )
                )
            buy_rows = [token_buttons[:2], token_buttons[2:]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="← Назад", callback_data="buy_back"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"buy_refresh_{token_address}")
                ],
                buy_rows[0],
                buy_rows[1],
                [
                    InlineKeyboardButton(text=f"Купить X {token_input.upper()}", callback_data=f"buy_custom_{token_address}")
                ]
            ])
            await state.update_data(token_address=token_address)
            await message.answer(token_info, reply_markup=keyboard)

            
        except Exception as route_error:
            logger.error(f"🔍 Ошибка при получении маршрута: {str(route_error)}")
            # --- Формируем карточку токена даже если Jupiter API вернул ошибку ---
            route_exists = False
            try:
                decimals = await jupiter.get_token_decimals(token_address)
            except Exception:
                decimals = 6
            out_amount = 0.0
            price_impact = 0.0
            swap_usd_value = None
            market_name = token_input.upper()
            token_info = f"Купить ${token_input.upper()} — ({market_name})\n"
            token_info += f"{token_address}\n\n"
            token_info += f"Баланс: {user_sol_balance} SOL\n"
            token_info += f"Price: недоступно\n"
            token_info += f"Объем сделки: недоступно\n"
            token_info += "LIQ: недоступно\n"
            token_info += "MC: недоступно\n"
            token_info += "Децентрализован ✅\n\n"
            token_info += f"1 SOL ⇄ ? {token_input.upper()}\n"
            token_info += f"Влияние на цену: недоступно"
            amounts_sol = [0.01, 0.1, 0.5, 1]
            token_buttons = []
            for sol_amt in amounts_sol:
                token_amt_str = f"?"
                token_buttons.append(
                    InlineKeyboardButton(
                        text=f"Купить {token_amt_str} {token_input.upper()}",
                        callback_data=f"buy_{sol_amt}_{token_address}"
                    )
                )
            buy_rows = [token_buttons[:2], token_buttons[2:]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="← Назад", callback_data="buy_back"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data=f"buy_refresh_{token_address}")
                ],
                buy_rows[0],
                buy_rows[1],
                [
                    InlineKeyboardButton(text=f"Купить X {token_input.upper()}", callback_data=f"buy_custom_{token_address}")
                ]
            ])
            await state.update_data(token_address=token_address)
            await message.answer(token_info, reply_markup=keyboard)
            # Не сбрасываем состояние, чтобы пользователь мог попробовать еще раз
        
    except Exception as e:
        logger.error(f"[CRITICAL] Ошибка в process_token: {str(e)}", exc_info=True)
        try:
            await message.answer(f"❌ Произошла внутренняя ошибка при обработке вашего запроса. Попробуйте еще раз или введите другой токен.\n\nДетали для поддержки: {str(e)}")
        except Exception as send_error:
            logger.error(f"[CRITICAL] Не удалось отправить сообщение об ошибке пользователю: {send_error}")
        # Не сбрасываем состояние, чтобы пользователь мог попробовать еще раз

@router.callback_query(F.data.startswith("buy_"))
async def process_buy_callback(callback: CallbackQuery, state: FSMContext):
    # СРАЗУ отвечаем на callback, чтобы избежать TelegramBadRequest
    try:
        await callback.answer()
    except Exception:
        pass  # Если уже отвечали, игнорируем ошибку

    action, *params = callback.data.split("_")
    
    # Проверяем, что действие не является 'custom' перед доступом к params[-1]
    if len(params) > 0:
        token_address = params[-1]
    else:
        token_address = None
    
    if callback.data.startswith("buy_back"):
        await state.clear()
        await callback.message.delete()
        return
        
    if callback.data.startswith("buy_refresh_"):
        # Обновляем информацию о токене
        await process_token(callback.message, state)
        return
        
    if callback.data.startswith("buy_custom_"):
        await state.set_state(BuyStates.waiting_for_amount)
        # Сохраняем адрес токена в данных состояния
        await state.update_data(token_address=token_address)
        
        # Запрашиваем сумму для покупки
        await callback.message.answer("Введите количество SOL для покупки:")
        return
        
    # Обработка покупки
    try:
        amount = float(params[0])
        user_id = callback.from_user.id
        
        # Проверяем, что сумма положительная
        if amount <= 0:
            await callback.message.answer("❌ Сумма должна быть больше 0. Пожалуйста, выберите положительную сумму.")
            return
        
        await callback.message.answer(f"⏳ Выполняется покупка {amount} SOL. Пожалуйста, подождите...")
        
        # Получаем ключи пользователя из Firebase
        user_pubkey, user_privkey = await get_user_wallet(user_id)
        
        # Получаем маршрут и выполняем своп
        route = await jupiter.get_best_route(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint=token_address,
            amount=int(amount * 1000000000),
            slippage=10.0
        )
        
        tx_url = await jupiter.execute_swap(
            user_pubkey=user_pubkey,
            user_privkey=user_privkey,
            route=route
        )
        
        # Проверяем, содержит ли ответ ошибку
        if tx_url.startswith("❌ Ошибка"):
            error_msg = tx_url.replace("❌ Ошибка: ", "")
            # Логируем неудачную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="buy",
                token=token_address,
                amount=amount,
                status="error",
                error=error_msg
            )
            await callback.message.answer(tx_url)
        else:
            # Извлекаем сигнатуру транзакции из URL
            tx_signature = tx_url.split('/')[-1]
            
            # Логируем успешную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="buy",
                token=token_address,
                amount=amount,
                status="success",
                tx_signature=tx_signature
            )
            
            await callback.message.answer(
                f"✅ Покупка выполнена успешно!\n"
                f"Количество: {amount} SOL\n"
                f"Транзакция: {tx_url}"
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing buy: {error_msg}")
        
        # Логируем ошибку транзакции
        log_transaction(
            user_id=callback.from_user.id,
            tx_type="buy",
            token=token_address,
            amount=amount if 'amount' in locals() else 0,
            status="error",
            error=error_msg
        )
        
        await callback.message.answer(f"❌ Ошибка при выполнении покупки: {error_msg}")
    finally:
        await state.clear()

@router.message(BuyStates.waiting_for_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    try:
        # Получаем сохраненный адрес токена
        data = await state.get_data()
        token_address = data.get('token_address')
        user_id = message.from_user.id
        
        if not token_address:
            await message.answer("❌ Ошибка: не найден адрес токена. Начните покупку заново.")
            await state.clear()
            return
            
        try:
            amount = float(message.text)
            if amount <= 0:
                await message.answer("❌ Сумма должна быть больше 0")
                return
        except ValueError:
            await message.answer("❌ Пожалуйста, введите корректное число")
            return
            
        # Выполняем покупку напрямую
        await message.answer(f"⏳ Выполняется покупка {amount} SOL. Пожалуйста, подождите...")
        
        # Получаем ключи пользователя из Firebase
        user_pubkey, user_privkey = await get_user_wallet(user_id)
        
        # Получаем маршрут и выполняем своп
        route = await jupiter.get_best_route(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint=token_address,
            amount=int(amount * 1000000000),
            slippage=10.0
        )
        
        tx_url = await jupiter.execute_swap(
            user_pubkey=user_pubkey,
            user_privkey=user_privkey,
            route=route
        )
        
        # Проверяем результат
        if tx_url.startswith("❌ Ошибка"):
            error_msg = tx_url.replace("❌ Ошибка: ", "")
            # Логируем неудачную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="buy",
                token=token_address,
                amount=amount,
                status="error",
                error=error_msg
            )
            await message.answer(tx_url)
        else:
            # Извлекаем сигнатуру транзакции из URL
            tx_signature = tx_url.split('/')[-1]
            
            # Логируем успешную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="buy",
                token=token_address,
                amount=amount,
                status="success",
                tx_signature=tx_signature
            )
            
            await message.answer(
                f"✅ Покупка выполнена успешно!\n"
                f"Количество: {amount} SOL\n"
                f"Транзакция: {tx_url}"
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing custom amount: {error_msg}")
        
        # Логируем ошибку транзакции
        log_transaction(
            user_id=message.from_user.id,
            tx_type="buy",
            token=token_address if 'token_address' in locals() else 'unknown',
            amount=amount if 'amount' in locals() else 0,
            status="error",
            error=error_msg
        )
        
        await message.answer(f"❌ Ошибка при выполнении покупки: {error_msg}")
    finally:
        await state.clear() 