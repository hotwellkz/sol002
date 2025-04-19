from aiogram import Router, types
from aiogram.filters import Command
from loguru import logger
from services.wallet import WalletService
from services.solana_service import SolanaService

router = Router()
wallet_service = WalletService()
solana_service = SolanaService()

@router.message(Command("balance"))
async def cmd_balance(message: types.Message, state=None):
    """Обработчик команды /balance: показывает SOL и все токены с ненулевым балансом (как /start)"""
    user_id = message.from_user.id
    logger.info(f"User {user_id} requested balance (show all tokens with nonzero balance)")
    try:
        # Получаем кошелек пользователя
        wallet = await wallet_service.get_wallet(user_id)
        if not wallet:
            await message.answer("У вас еще нет кошелька. Используйте команду /start для его создания.")
            return

        public_key = wallet['public_key']
        # Получаем баланс SOL
        sol_balance = await solana_service.get_sol_balance(public_key)
        from services.price_service import PriceService
        sol_price_usd = 0.0
        try:
            sol_price_usd = await PriceService().get_sol_price()
        except Exception:
            pass
        usd_value = float(sol_balance) * sol_price_usd if sol_price_usd else 0.0

        # Получаем токены с ненулевым балансом
        tokens = await solana_service.get_wallet_tokens(public_key)

        # Формируем сообщение
        text = (
            f"👇 Ваш кошелек:\n"
            f"`{public_key}`\n\n"
            f"💰 Балансы:\n"
        )
        text += f"- SOL: {sol_balance} (~${usd_value:.2f})\n"

        # Сопоставляем mint-адреса с тикерами (если возможно)
        from config import SOLANA_TOKEN_ADDRESSES
        mint_to_ticker = {v: k for k, v in SOLANA_TOKEN_ADDRESSES.items()}
        for mint, raw_amount in tokens.items():
            balance = await solana_service.get_token_balance(public_key, mint)
            ticker = mint_to_ticker.get(mint, mint[:6])
            text += f"- {ticker}: {balance}\n"

        text += "\nЧтобы увидеть новые токены — сначала купите их через бота."

        # Получаем клавиатуру, если есть
        try:
            from keyboards.inline import get_main_keyboard
            keyboard = get_main_keyboard()
        except Exception:
            keyboard = None

        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        logger.info(f"Balance info (all tokens) sent to user {user_id}")
    except Exception as e:
        logger.error(f"Error in balance command for user {user_id}: {e}")
        await message.answer("Произошла ошибка при получении баланса. Пожалуйста, попробуйте позже.")