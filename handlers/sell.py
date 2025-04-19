from aiogram import Router, F
from keyboards.inline import process_sell_callback
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
from loguru import logger
from services.jupiter_service import JupiterService
from services.firebase_service import FirebaseService
from services.solana_service import SolanaService
from config import SOLANA_RPC_URL, SOLANA_TOKEN_ADDRESSES, JUPITER_PLATFORM_FEE_BPS
from solana.publickey import PublicKey
from utils import log_transaction

router = Router(name='sell')
jupiter = JupiterService()
firebase = FirebaseService()
solana_service = SolanaService()

class SellStates(StatesGroup):
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

@router.message(Command("sell"))
async def cmd_sell(message: Message, state: FSMContext):
    """Обработчик команды /sell"""
    # Сначала завершаем все текущие состояния
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
    # Имитация callback для повторного использования логики process_sell_callback
    class FakeCallback:
        def __init__(self, message):
            self.from_user = message.from_user
            self.message = message
        async def answer(self, *args, **kwargs):
            pass
    fake_callback = FakeCallback(message)
    await process_sell_callback(fake_callback)
    await state.set_state(SellStates.waiting_for_token)



@router.message(SellStates.waiting_for_amount)
async def process_amount_sell(message: Message, state: FSMContext):
    """
    Обработчик ввода суммы для продажи
    Выполняет продажу токена через Jupiter API
    """
    try:
        # Получаем сохраненный символ токена
        data = await state.get_data()
        token_symbol_or_address = data.get('token_symbol_or_address')
        
        if not token_symbol_or_address:
            await message.answer("❌ Ошибка: Не удалось получить информацию о токене")
            await state.clear()
            return

        # Проверяем, что введена сумма
        try:
            amount = float(message.text)
            if amount <= 0:
                raise ValueError("Сумма должна быть больше 0")
        except ValueError:
            await message.answer("❌ Пожалуйста, введите корректную сумму, например: 1.0 или 0.5")
            return

        # Получаем адрес токена (mint), выбранного пользователем
        token_address = token_symbol_or_address
        # ВАЖНО: Только один токен! Не перебираем все токены!
        logger.info(f"[SELL] Продажа токена: {token_address}, сумма: {amount}")
        # Если потребуется получить адрес по символу — используем только этот символ
        # Запрещено сканировать все токены! Если где-то происходит цикл — это ошибка!

        # Получаем публичный и приватный ключи пользователя
        public_key, private_key = await get_user_wallet(message.from_user.id)
        
        # Выполняем продажу токена (операция только по одному токену)
        result = await jupiter.execute_sell(
            user_pubkey=public_key,
            user_privkey=private_key,
            token_address=token_address,
            amount=amount
        )
        # Контроль: если вдруг где-то цикл по токенам — логируем ошибку
        if isinstance(result, list):
            logger.error("[SELL] Получен результат в виде списка — возможно цикл по токенам! Это ошибка.")
            await message.answer("❌ Внутренняя ошибка: цикл по токенам при продаже. Обратитесь к поддержке.")
            await state.clear()
            return

        # Очищаем состояние
        await state.clear()

        # Отправляем результат пользователю
        if result.startswith("❌"):
            await message.answer(result)
        else:
            await message.answer(
                f"✅ Продажа выполнена успешно!\n"
                f"Токен: {token_symbol_or_address}\n"
                f"Сумма: {amount}\n"
                f"Комиссия: {JUPITER_PLATFORM_FEE_BPS/100}%\n"
                f"Транзакция: {result}"
            )

    except Exception as e:
        logger.error(f"Ошибка при продаже токена: {str(e)}")
        await message.answer(f"❌ Ошибка при продаже токена: {str(e)}")
        await state.clear()

@router.callback_query(F.data.startswith("sell_confirm"))
async def process_sell_confirmation(callback: CallbackQuery, state: FSMContext):
    """Обработка подтверждения продажи"""
    try:
        user_id = callback.from_user.id
        data = await state.get_data()
        token_address = data.get('token_address')
        amount = data.get('amount')
        
        if not token_address or not amount:
            await callback.message.answer("❌ Ошибка: недостаточно данных для продажи")
            await state.clear()
            return
            
        await callback.message.edit_text(
            "⏳ Выполняется продажа токенов. Пожалуйста, подождите..."
        )
        
        # Получаем ключи пользователя
        user_pubkey, user_privkey = await get_user_wallet(user_id)
        
        # Получаем маршрут и выполняем своп
        route = await jupiter.get_best_route(
            input_mint=token_address,
            output_mint="So11111111111111111111111111111111111111112",  # SOL
            amount=int(amount * 1000000000),
            slippage=10.0
        )
        
        tx_url = await jupiter.execute_swap(
            user_pubkey=user_pubkey,
            user_privkey=user_privkey,
            route=route
        )
        
        if tx_url.startswith("❌ Ошибка"):
            error_msg = tx_url.replace("❌ Ошибка: ", "")
            # Логируем неудачную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="sell",
                token=token_address,
                amount=amount,
                status="error",
                error=error_msg
            )
            await callback.message.edit_text(tx_url)
        else:
            # Извлекаем сигнатуру транзакции из URL
            tx_signature = tx_url.split('/')[-1]
            
            # Логируем успешную транзакцию
            log_transaction(
                user_id=user_id,
                tx_type="sell",
                token=token_address,
                amount=amount,
                status="success",
                tx_signature=tx_signature
            )
            
            # Определяем название токена для отображения
            token_name = next(
                (name for name, addr in SOLANA_TOKEN_ADDRESSES.items() if addr == token_address),
                token_address
            )
            
            await callback.message.edit_text(
                f"✅ Продажа выполнена успешно!\n"
                f"Продано: {amount} {token_name}\n"
                f"Транзакция: {tx_url}"
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing sell confirmation: {error_msg}")
        
        # Логируем ошибку транзакции
        log_transaction(
            user_id=callback.from_user.id,
            tx_type="sell",
            token=token_address if 'token_address' in locals() else 'unknown',
            amount=amount if 'amount' in locals() else 0,
            status="error",
            error=error_msg
        )
        
        await callback.message.edit_text(f"❌ Ошибка при выполнении продажи: {error_msg}")
    finally:
        await state.clear() 