from aiogram import Router, types, F
from aiogram.filters import Command
from loguru import logger
from services.firebase_service import FirebaseService
from services.solana_service import SolanaService
from services.price_service import PriceService
from services.wallet import WalletService
from solana.keypair import Keypair
from base58 import b58encode
from keyboards.inline import get_main_keyboard
import json

router = Router(name='start')
firebase = FirebaseService()
solana = SolanaService()
price_service = PriceService()
wallet_service = WalletService()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    try:
        user_id = message.from_user.id
        logger.info(f"User {user_id} started the bot")
        
        # Проверяем наличие кошелька в Firebase
        wallet_data = await wallet_service.get_wallet(user_id)
        
        if not wallet_data:
            # Создаем новый кошелек через WalletService, который правильно шифрует ключи
            wallet_data = await wallet_service.create_wallet(user_id)
            logger.info(f"Created new wallet for user {user_id}")
        
        # Получаем баланс SOL
        sol_balance = await solana.get_sol_balance(wallet_data['public_key'])
        sol_price_usd = await price_service.get_sol_price()

        # Получаем токены с ненулевым балансом
        tokens = await solana.get_wallet_tokens(wallet_data['public_key'])

        # Формируем сообщение
        text = (
            f"👇 Ваш кошелек:\n"
            f"`{wallet_data['public_key']}`\n\n"
            f"💰 Балансы:\n"
        )
        usd_value = float(sol_balance) * sol_price_usd
        text += f"- SOL: {sol_balance} (~${usd_value:.2f})\n"

        # Сопоставляем mint-адреса с тикерами (если возможно)
        from config import SOLANA_TOKEN_ADDRESSES
        mint_to_ticker = {v: k for k, v in SOLANA_TOKEN_ADDRESSES.items()}
        for mint, raw_amount in tokens.items():
            # Получаем баланс токена с учетом decimals
            balance = await solana.get_token_balance(wallet_data['public_key'], mint)
            ticker = mint_to_ticker.get(mint, mint[:6])
            text += f"- {ticker}: {balance}\n"

        text += "\nЧтобы увидеть новые токены — сначала купите их через бота."

        # Получаем клавиатуру
        keyboard = get_main_keyboard()

        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        logger.info(f"Welcome message sent to user {user_id}")
        
    except Exception as e:
        error_msg = f"Error in start handler: {str(e)}"
        logger.error(error_msg)
        await message.answer("❌ Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже.")
