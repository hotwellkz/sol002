from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F, Router
from aiogram.types import CallbackQuery
from loguru import logger
import decimal
from services.firebase_service import FirebaseService
from services.solana_service import SolanaService
from services.price_service import PriceService

router = Router(name='inline_kb')
firebase = FirebaseService()
solana = SolanaService()
price_service = PriceService()

def get_main_keyboard() -> InlineKeyboardMarkup:
    """Создает основную клавиатуру с кнопками"""
    buttons = [
        [
            InlineKeyboardButton(text="Купить", callback_data="buy"),
            InlineKeyboardButton(text="Продать", callback_data="sell")
        ],
        [
            InlineKeyboardButton(text="Вывести", callback_data="withdraw"),
            InlineKeyboardButton(text="Экспорт ключей", callback_data="export_keys")
        ],
        [
            InlineKeyboardButton(text="Баланс", callback_data="balance"),
            InlineKeyboardButton(text="Обновить", callback_data="refresh")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

from aiogram.fsm.context import FSMContext
from handlers.buy import BuyStates

@router.callback_query(F.data == "buy")
async def process_buy_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки Купить"""
    await state.set_state(BuyStates.waiting_for_token)
    await callback.message.answer("Введите символ токена или адрес для покупки")
    await callback.answer()

def get_tokens_keyboard(tokens: list) -> InlineKeyboardMarkup:
    """
    Формирует inline-клавиатуру с токенами в 2 колонки и кнопками 'Обновить', 'Назад'.
    tokens: список словарей вида {"symbol": str, "amount": float, "usd": float}
    """
    buttons = []
    row = []
    for idx, token in enumerate(tokens):
        btn = InlineKeyboardButton(
            text=f"{token['symbol']}",
            callback_data=f"sell_token_{token['symbol']}"
        )
        row.append(btn)
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Добавляем кнопки управления
    buttons.append([
        InlineKeyboardButton(text="⟳ Обновить", callback_data="sell_refresh"),
        InlineKeyboardButton(text="← Назад", callback_data="sell_back")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

class SellStates(StatesGroup):
    waiting_for_percent = State()


@router.callback_query(F.data.startswith("sell_percent_custom_"))
async def sell_custom_percent_callback(callback: CallbackQuery, state: FSMContext):
    token_symbol = callback.data.replace("sell_percent_custom_", "")
    # Добавим клавиатуру с кнопкой отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="sell_cancel_custom_percent")]
    ])
    await callback.message.answer(
        f"<b>Введите число от 1 до 100</b>\nЭто процент баланса, который вы хотите продать для <b>{token_symbol}</b>.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(SellStates.waiting_for_percent)
    await state.update_data(token_symbol=token_symbol)
    await callback.answer()

@router.message(SellStates.waiting_for_percent)
async def process_custom_percent(message: Message, state: FSMContext):
    text = message.text.strip().replace('%', '')
    if not text.isdigit():
        await message.answer("❗ Введите только число от 1 до 100.")
        return
    percent = int(text)
    if not (1 <= percent <= 100):
        await message.answer("❗ Введите число от 1 до 100.")
        return
    data = await state.get_data()
    token_symbol = data.get("token_symbol")
    user_id = message.from_user.id
    wallet = await firebase.get_user_wallet(user_id)
    if not wallet:
        await message.answer("❌ Кошелек не найден. Используйте /start для создания.")
        await state.clear()
        return
    from config import SOLANA_TOKEN_ADDRESSES
    address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
    amount = await solana.get_token_balance(wallet['public_key'], address)
    if not amount or amount == 0:
        await message.answer("❌ Нет баланса для продажи.")
        await state.clear()
        return
    sell_amount = amount * percent / 100
    msg = await message.answer(f"⏳ Проводим транзакцию продажи {sell_amount:.6f} {token_symbol} ({percent}% от баланса)...")
    from config import SOLANA_TOKEN_ADDRESSES
    from services.jupiter_service import JupiterService
    jupiter_service = JupiterService()
    address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
    try:
        tx_result = await jupiter_service.execute_sell(
            user_pubkey=wallet['public_key'],
            user_privkey=wallet['private_key'],
            token_address=address,
            amount=sell_amount
        )
        solscan_url = None
        tx_status = ""
        if isinstance(tx_result, str) and tx_result.startswith("https://solscan.io/tx/"):
            solscan_url = tx_result
            tx_status = "🟢 Продажа выполнена!"
        elif isinstance(tx_result, str):
            tx_status = f"🔴 Ошибка: {tx_result}"
        else:
            tx_status = f"🔴 Неизвестный результат: {tx_result}"
        sol_price_usd = await price_service.get_sol_price()
        price = await price_service.get_token_price_jupiter(address, jupiter_service, sol_price_usd)
        sol_amount = None
        if price:
            sol_amount = sell_amount * price / sol_price_usd
        text_lines = [
            f"<b>Продажа {sell_amount:.6f} {token_symbol}</b>"
        ]
        if price:
            text_lines.append(f"Цена: <b>${price:.4f}</b> за 1 {token_symbol}")
        else:
            text_lines.append("Цена: нет данных")
        if sol_amount:
            text_lines.append(f"Получено: <b>{sol_amount:.6f} SOL</b> (~${sol_amount * sol_price_usd:.2f})")
        text_lines.append(tx_status)
        if solscan_url:
            text_lines.append(f'<a href="{solscan_url}">Посмотреть на Solscan</a>')
        text = "\n".join(text_lines)
        buttons = [
            [InlineKeyboardButton(text="← Назад", callback_data="sell")],
        ]
        if solscan_url:
            buttons.append([InlineKeyboardButton(text="Посмотреть на Solscan", url=solscan_url)])
        buttons.append([InlineKeyboardButton(text="Продать", callback_data=f"sell_token_{token_symbol}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при продаже: {str(e)}")
    await state.clear()

@router.callback_query(F.data == "sell_cancel_custom_percent")
async def cancel_custom_percent(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("❌ Ввод процента отменён.")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data.startswith("sell_percent_"))
async def process_sell_percent_callback(callback: CallbackQuery):
    """Обработчик кнопок 25%, 50%, 75%, 100% и Продать X% для мгновенной продажи токена."""
    user_id = callback.from_user.id
    try:
        import re
        # Всегда получаем wallet и address вне зависимости от формата
        wallet = await firebase.get_user_wallet(user_id)
        if not wallet:
            await callback.message.answer("❌ Кошелек не найден. Используйте /start для создания.")
            return
        from config import SOLANA_TOKEN_ADDRESSES
        # Новый формат: sell_percent_100_SYMBOL:точный_баланс
        if ':' in callback.data:
            m = re.match(r"sell_percent_(\d+)_([A-Za-z0-9]+):(.*)", callback.data)
            if not m:
                await callback.message.answer("Ошибка: некорректные данные кнопки.")
                return
            percent_raw, token_symbol, amount_str = m.groups()
            address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
            try:
                sell_amount = float(amount_str)
            except Exception:
                await callback.message.answer("Ошибка: не удалось разобрать баланс для продажи.")
                return
            percent = int(percent_raw)
        else:
            m = re.match(r"sell_percent_(\d+|custom)_(.+)", callback.data)
            if not m:
                await callback.message.answer("Ошибка: некорректные данные кнопки.")
                return
            percent_raw, token_symbol = m.groups()
            address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
            amount = await solana.get_token_balance(wallet['public_key'], address)
            if not amount or amount == 0:
                await callback.message.answer("❌ Нет баланса для продажи.")
                return
            # Если custom - запросить ввод процента
            if percent_raw == "custom":
                await callback.message.answer("Введите процент (от 1 до 100), который хотите продать, например: 37")
                # Здесь можно реализовать FSM для ожидания ввода процента
                return
            percent = int(percent_raw)
            if percent < 1 or percent > 100:
                await callback.message.answer("Ошибка: процент должен быть от 1 до 100.")
                return
            sell_amount = amount * percent / 100
        # Сообщение о начале транзакции
        msg = await callback.message.answer(f"⏳ Проводим транзакцию продажи {sell_amount:.6f} {token_symbol} ({percent}% от баланса)...")
        # Получаем адрес токена
        from config import SOLANA_TOKEN_ADDRESSES
        from services.jupiter_service import JupiterService
        from utils import to_lamports
        jupiter_service = JupiterService()
        address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
        # Получаем decimals токена
        decimals = await jupiter_service.get_token_decimals(address)
        amount_lamports = to_lamports(sell_amount, decimals)
        if amount_lamports < 1:
            await msg.edit_text(f"❗️ Слишком маленькое количество для продажи. Минимально допустимое — 1 минимальная единица токена (lamports).\n\nВаш баланс: {sell_amount} {token_symbol}")
            return
        # Выполняем продажу через Jupiter
        try:
            tx_result = await jupiter_service.execute_sell(
                user_pubkey=wallet['public_key'],
                user_privkey=wallet['private_key'],
                token_address=address,
                amount=amount_lamports
            )
            # --- Формируем красивое сообщение ---
            solscan_url = None
            tx_status = ""
            # Если tx_result — ссылка на Solscan
            if isinstance(tx_result, str) and tx_result.startswith("https://solscan.io/tx/"):
                solscan_url = tx_result
                tx_status = "🟢 Продажа выполнена!"
            elif isinstance(tx_result, str):
                tx_status = f"🔴 Ошибка: {tx_result}"
            else:
                tx_status = f"🔴 Неизвестный результат: {tx_result}"
            # Получаем цену токена и сумму в SOL
            sol_price_usd = await price_service.get_sol_price()
            price = await price_service.get_token_price_jupiter(address, jupiter_service, sol_price_usd)
            sol_amount = None
            if price:
                sol_amount = sell_amount * price / sol_price_usd
            # Текст
            text_lines = [
                f"<b>Продажа {sell_amount:.6f} {token_symbol}</b>"
            ]
            if price:
                text_lines.append(f"Цена: <b>${price:.4f}</b> за 1 {token_symbol}")
            else:
                text_lines.append("Цена: нет данных")
            if sol_amount:
                text_lines.append(f"Получено: <b>{sol_amount:.6f} SOL</b> (~${sol_amount * sol_price_usd:.2f})")
            text_lines.append(tx_status)
            if solscan_url:
                text_lines.append(f'<a href="{solscan_url}">Посмотреть на Solscan</a>')
            text = "\n".join(text_lines)

            # Кнопки
            buttons = [
                [InlineKeyboardButton(text="← Назад", callback_data="sell")],
            ]
            if solscan_url:
                buttons.append([InlineKeyboardButton(text="Посмотреть на Solscan", url=solscan_url)])
            buttons.append([InlineKeyboardButton(text="Продать", callback_data=f"sell_token_{token_symbol}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await msg.edit_text(text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка при продаже: {str(e)}")
    except Exception as e:
        logger.error(f"Error in process_sell_percent_callback: {e}")
        await callback.message.answer(f"Ошибка при продаже: {str(e)}")
    await callback.answer()

@router.callback_query(F.data.startswith("sell_token_"))
async def process_sell_token_callback(callback: CallbackQuery):
    """Показывает подробную информацию о выбранном токене и кнопки для выбора процента продажи."""
    user_id = callback.from_user.id
    try:
        token_symbol = callback.data.replace("sell_token_", "")
        wallet = await firebase.get_user_wallet(user_id)
        if not wallet:
            await callback.message.answer("❌ Кошелек не найден. Используйте /start для создания.")
            return
        sol_price_usd = await price_service.get_sol_price()
        from config import SOLANA_TOKEN_ADDRESSES
        from services.jupiter_service import JupiterService
        jupiter_service = JupiterService()
        address = SOLANA_TOKEN_ADDRESSES.get(token_symbol, token_symbol)
        amount = await solana.get_token_balance(wallet['public_key'], address)
        # Получаем цену токена через Jupiter или CoinGecko
        price = await price_service.get_token_price_jupiter(address, jupiter_service, sol_price_usd)
        if not price:
            price = await price_service.get_token_price_usd(address)
        try:
            usd_value = float(amount) * float(price) if price else 0
            if usd_value > 1_000_000:  # диагностический порог
                logger.warning(f"[SELL TOKENS] usd_value слишком велик: amount={amount}, price={price}, usd_value={usd_value}")
        except Exception as e:
            logger.error(f"Ошибка при расчёте usd_value: amount={amount}, price={price}, error={e}")
            usd_value = 0
        # Формируем красивое сообщение
        text = (
            f"<b>Продать ${token_symbol}</b>\n"
            f"\n"
            f"Баланс: <b>{amount} {token_symbol}</b>  (<b>${usd_value:.2f}</b>)\n"
            f"Цена: <b>${price:.4f}</b> за 1 {token_symbol}" if price else "Цена: нет данных" 
            f"\n"
            f"\n<i>Выберите, какую часть баланса продать:</i>"
        )
        # Клавиатура
        # Формируем кнопки с точным балансом для 100%
        percent_buttons = []
        for percent in [25, 50, 75, 100]:
            if percent == 100:
                callback_data = f"sell_percent_{percent}_{token_symbol}:{amount}"
            else:
                callback_data = f"sell_percent_{percent}_{token_symbol}"
            percent_buttons.append(InlineKeyboardButton(text=f"{percent}%", callback_data=callback_data))
        buttons = [
            [InlineKeyboardButton(text="← Назад", callback_data="sell")],
            [InlineKeyboardButton(text="⟳ Обновить", callback_data=f"sell_token_{token_symbol}")],
            percent_buttons,
            [InlineKeyboardButton(text="Продать X% ✍️", callback_data=f"sell_percent_custom_{token_symbol}")]
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in process_sell_token_callback: {e}")
        await callback.message.answer("Ошибка при получении информации о токене.")
    await callback.answer()

@router.callback_query(F.data == "sell")
async def process_sell_callback(callback: CallbackQuery):
    """Обработчик кнопки Продать. Показывает список токенов для продажи с клавиатурой."""
    user_id = callback.from_user.id
    try:
        wallet = await firebase.get_user_wallet(user_id)
        if not wallet:
            await callback.message.answer("❌ Кошелек не найден. Используйте /start для создания.")
            return
        # Получаем только токены с ненулевым балансом через SolanaService (mint: amount)
        try:
            tokens_raw = await solana.get_wallet_tokens(wallet['public_key'])
        except Exception as e:
            logger.error(f"Ошибка при получении токенов пользователя: {e}")
            await callback.message.answer("❌ Не удалось получить список токенов. Попробуйте позже.")
            await callback.answer()
            return

        if not tokens_raw:
            await callback.message.answer("У вас нет токенов для продажи.")
            await callback.answer()
            return

        sol_price_usd = 0.0
        try:
            sol_price_usd = await price_service.get_sol_price()
        except Exception as e:
            logger.error(f"Ошибка при получении цены SOL: {e}")

        from config import SOLANA_TOKEN_ADDRESSES
        mint_to_ticker = {v: k for k, v in SOLANA_TOKEN_ADDRESSES.items()}
        import asyncio
        from services.jupiter_service import JupiterService
        jupiter_service = JupiterService()
        async def get_usd(mint, amount):
            ticker = mint_to_ticker.get(mint, mint[:6])
            if ticker == 'SOL':
                return sol_price_usd, float(amount) * sol_price_usd
            # Получаем цену через Jupiter
            price_jup = None
            try:
                logger.debug(f"[SELL TOKENS][get_usd] mint={mint}, amount={amount} — вызов get_token_price_jupiter")
                price_jup = await price_service.get_token_price_jupiter(mint, jupiter_service, sol_price_usd)
                logger.debug(f"[SELL TOKENS][get_usd] mint={mint}, amount={amount} — результат get_token_price_jupiter: {price_jup} (type={type(price_jup)})")
            except Exception as e:
                logger.error(f"Ошибка Jupiter для {mint}: {e}")
            if price_jup:
                return price_jup, float(amount) * price_jup
            # Fallback — CoinGecko
            price_cg = None
            try:
                price_cg = await price_service.get_token_price_usd(mint)
            except Exception as e:
                logger.error(f"Ошибка CoinGecko для {mint}: {e}")
            if price_cg:
                return price_cg, float(amount) * price_cg
            return None, None
        try:
            tasks = [get_usd(mint, amount['amount'] if isinstance(amount, dict) else amount) for mint, amount in tokens_raw.items()]
            usd_results = await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Ошибка при получении цен токенов: {e}")
            await callback.message.answer("❌ Не удалось получить цены токенов. Попробуйте позже.")
            await callback.answer()
            return
        DECIMALS_OVERRIDE = {
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 6,  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 6,  # USDT
            '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R': 6,  # RAY
            '7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs': 8,  # ETH (Wormhole)
            'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': 6,  # ORCA
            # Добавьте другие mint при необходимости
        }
        tokens = []
        from utils import from_lamports
        for idx, (mint, amount) in enumerate(tokens_raw.items()):
            amount_val = amount['amount'] if isinstance(amount, dict) else amount
            price, _ = usd_results[idx]
            logger.debug(f"[SELL TOKENS] get_usd для mint={mint}, amount={amount_val}: price={price} (type={type(price)})")
            ticker = mint_to_ticker.get(mint, mint[:6])
            # Диагностика структуры
            if isinstance(price, dict):
                logger.error(f"[SELL TOKENS] Некорректный тип данных: price={price} (type={type(price)}), mint={mint}, amount={amount}")
                price = None
            try:
                if mint in DECIMALS_OVERRIDE:
                    decimals = DECIMALS_OVERRIDE[mint]
                else:
                    decimals = await jupiter_service.get_token_decimals(mint)
            except Exception as e:
                logger.error(f"Ошибка получения decimals для {mint}: {e}")
                decimals = 9
            try:
                amount_val = amount['amount'] if isinstance(amount, dict) else amount
                amount_display = from_lamports(int(amount_val), decimals)
                logger.debug(f"[SELL TOKENS] {ticker} mint={mint} amount={amount_val} decimals={decimals} display={amount_display}")
            except Exception as e:
                logger.error(f"[SELL TOKENS] Ошибка пересчёта: {e}")
                amount_display = amount
            try:
                usd = float(amount_display) * float(price) if price else 0
            except Exception as e:
                logger.error(f"[SELL TOKENS] Ошибка при расчёте usd для {ticker}: {e}")
                usd = 0
            tokens.append({
                "symbol": ticker,
                "amount": amount_display,
                "usd": usd,
                "price": price,
                "mint": mint
            })
        if not tokens:
            await callback.message.answer("У вас нет токенов для продажи.")
            await callback.answer()
            return
        # Оформление сообщения
        # Получаем баланс SOL отдельно
        sol_balance = 0.0
        try:
            sol_balance = await solana.get_sol_balance(wallet['public_key'])
        except Exception as e:
            logger.error(f"Ошибка при получении баланса SOL: {e}")
        text = (
            f"<b>Выберите токен для продажи 1/{len(tokens)}</b>\n"
            f"<b>Баланс:</b> <b>{sol_balance}</b> SOL (<b>${float(sol_balance)*sol_price_usd:.2f}</b>)\n"
            "\n"
        )
        for t in tokens:
            # Безопасное форматирование usd и price
            if isinstance(t['usd'], dict) or not isinstance(t['usd'], (float, int)):
                logger.error(f"[SELL TOKENS] Некорректный usd для токена {t['symbol']}: {t['usd']} (type={type(t['usd'])})")
                usd_str = "нет данных"
            else:
                usd_str = f"${t['usd']:.2f}"
            if isinstance(t['price'], dict) or not isinstance(t['price'], (float, int)):
                logger.error(f"[SELL TOKENS] Некорректный price для токена {t['symbol']}: {t['price']} (type={type(t['price'])})")
                price_str = ""
            else:
                price_str = f"@ ${t['price']:.4f}"
            # Форматирование количества токенов с учетом decimals (до 6 знаков после запятой, если мало)
            try:
                mint = t.get('mint', '')
                if mint and len(mint) > 20:
                    decimals = await jupiter_service.get_token_decimals(mint)
                else:
                    decimals = 9
            except Exception:
                decimals = 9
            try:
                from utils import format_token_amount
                amount_str = format_token_amount(t['amount'], decimals)
            except Exception:
                amount_str = str(t['amount'])
            text += (
                f"💰 <b>{t['symbol']}</b>\n"
                f"    └ <b>{amount_str}</b>   (<b>{usd_str}</b>)  {price_str}\n"
            )
        text += "\n<i>Нажмите на токен ниже для выбора, либо обновите список.</i>"
        await callback.message.answer(text, reply_markup=get_tokens_keyboard(tokens), parse_mode="HTML")
        logger.info(f"Пользователь {user_id} получил список токенов для продажи: {[t['symbol'] for t in tokens]}")
    except Exception as e:
        logger.error(f"Ошибка в process_sell_callback: {e}")
        await callback.message.answer("❌ Произошла ошибка при получении токенов для продажи. Попробуйте позже.")
    await callback.answer()


from aiogram.types import Message

from handlers.withdraw import cmd_withdraw_with_user_id

@router.callback_query(F.data == "withdraw")
async def process_withdraw_callback(callback: CallbackQuery, state=None):
    """Обработчик кнопки Вывести — вызывает функцию вывода с правильным user_id"""
    message = callback.message
    if state is None:
        from aiogram.fsm.context import FSMContext
        state = FSMContext(callback.bot, callback.from_user.id, callback.chat_instance)
    await cmd_withdraw_with_user_id(message, state, callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "export_keys")
async def process_export_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки 'Экспорт ключей' — теперь как команда /export_keys: предупреждение и подтверждение."""
    try:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_export"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_export")
                ]
            ]
        )
        await callback.message.answer(
            "⚠️ ВНИМАНИЕ! Важная информация о безопасности!\n\n"
            "Вы запросили экспорт приватного ключа вашего кошелька. "
            "Пожалуйста, помните:\n\n"
            "1. НИКОГДА не передавайте приватный ключ третьим лицам\n"
            "2. Храните ключ в надежном месте\n"
            "3. Любой, кто получит доступ к ключу, получит полный контроль над кошельком\n\n"
            "Вы уверены, что хотите продолжить?",
            reply_markup=keyboard
        )
        from handlers.export_keys import ExportStates
        await state.set_state(ExportStates.waiting_for_confirmation)
        logger.info(f"User {callback.from_user.id} initiated export keys via button")
    except Exception as e:
        logger.error(f"Error in export keys callback: {e}")
        await callback.message.answer("Произошла ошибка при экспорте ключей. Попробуйте позже.")
    await callback.answer()

@router.callback_query(F.data == "balance")
async def process_balance_callback(callback: CallbackQuery):
    """Обработчик кнопки Баланс"""
    user_id = callback.from_user.id
    try:
        wallet = await firebase.get_user_wallet(user_id)
        if wallet:
            balances = await solana.get_all_balances(wallet['public_key'])
            sol_price_usd = await price_service.get_sol_price()
            
            text = f"💰 Балансы:\n"
            for token, balance in balances.items():
                if token == 'SOL':
                    usd_value = float(balance) * sol_price_usd
                    text += f"- {token}: {balance} (~${usd_value:.2f})\n"
                else:
                    text += f"- {token}: {balance}\n"
            
            await callback.message.answer(text)
        else:
            await callback.message.answer("❌ Кошелек не найден")
    except Exception as e:
        logger.error(f"Error in balance check for user {user_id}: {e}")
        await callback.message.answer("Произошла ошибка при получении баланса")
    await callback.answer()

@router.callback_query(F.data == "refresh")
async def process_refresh_callback(callback: CallbackQuery):
    """Обработчик кнопки Обновить"""
    user_id = callback.from_user.id
    try:
        wallet = await firebase.get_user_wallet(user_id)
        if not wallet:
            await callback.answer("❌ Кошелек не найден")
            return
            
        balances = await solana.get_all_balances(wallet['public_key'])
        sol_price_usd = await price_service.get_sol_price()
        
        text = (
            f"👇 Ваш кошелек:\n"
            f"`{wallet['public_key']}`\n\n"
            f"💰 Балансы:\n"
        )
        
        for token, balance in balances.items():
            if token == 'SOL':
                usd_value = float(balance) * sol_price_usd
                text += f"- {token}: {balance} (~${usd_value:.2f})\n"
            else:
                text += f"- {token}: {balance}\n"
        
        text += "\nНажмите кнопку «Обновить», чтобы обновить ваш текущий баланс."
        
        await callback.message.edit_text(
            text,
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer("✅ Баланс обновлен")
        
    except Exception as e:
        logger.error(f"Error in refresh for user {user_id}: {e}")
        await callback.answer("❌ Ошибка при обновлении")
