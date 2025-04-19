from typing import Union, Tuple, Optional, Literal
from decimal import Decimal
import decimal

from loguru import logger
from datetime import datetime
import sys
from config import LOG_FILE

# Константы
DEFAULT_SLIPPAGE = 1.0  # 1%
MIN_SLIPPAGE = 0.1     # 0.1%
MAX_SLIPPAGE = 10.0    # 10%
LAMPORTS_PER_SOL = 1_000_000_000  # 1 SOL = 10^9 lamports

# Настройка логирования транзакций
logger.remove()  # Удаляем стандартный обработчик

# Добавляем обработчик для вывода в консоль
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# Добавляем обработчик для записи транзакций в файл
logger.add(
    LOG_FILE,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    filter=lambda record: "transaction" in record["extra"],
    rotation="1 day",
    retention="30 days"
)

TransactionType = Literal["buy", "sell", "withdraw"]

def validate_slippage(slippage: Union[float, str, None] = None) -> float:
    """
    Проверка и нормализация значения slippage
    
    Args:
        slippage: Значение проскальзывания в процентах (0.1-10)
        
    Returns:
        float: Нормализованное значение slippage
        
    Raises:
        ValueError: Если значение slippage вне допустимого диапазона
    """
    try:
        # Если slippage не указан, используем значение по умолчанию
        if slippage is None:
            logger.debug(f"Using default slippage: {DEFAULT_SLIPPAGE}%")
            return DEFAULT_SLIPPAGE
            
        # Преобразуем в float если передано строкой
        slip = float(slippage)
        
        # Проверяем диапазон
        if slip < MIN_SLIPPAGE or slip > MAX_SLIPPAGE:
            raise ValueError(
                f"Slippage должен быть между {MIN_SLIPPAGE}% и {MAX_SLIPPAGE}%"
            )
            
        logger.debug(f"Validated slippage: {slip}%")
        return slip
        
    except ValueError as e:
        logger.error(f"Invalid slippage value: {slippage}")
        raise ValueError(f"Неверное значение slippage: {str(e)}")

def to_lamports(amount: Union[float, str, Decimal], decimals: int = 9) -> int:
    """
    Конвертация токенов в минимальные единицы (lamports для SOL, 
    или минимальные единицы для других токенов)
    
    Args:
        amount: Количество токенов
        decimals: Количество десятичных знаков токена (9 для SOL)
        
    Returns:
        int: Количество в минимальных единицах
        
    Raises:
        ValueError: Если передано некорректное значение
    """
    try:
        # Преобразуем в Decimal для точных вычислений
        value = Decimal(str(amount))
        
        # Проверяем что значение положительное
        if value <= 0:
            # Возвращаем 0, чтобы бизнес-логика могла обработать "пыль"
            logger.debug(f"to_lamports: amount <= 0, возвращаю 0 (amount={amount})")
            return 0
        # Конвертируем в минимальные единицы
        lamports = int(value * Decimal(10 ** decimals))
        logger.debug(f"Converted {amount} tokens to {lamports} lamports (decimals={decimals})")
        return lamports
        
    except (ValueError, decimal.InvalidOperation) as e:
        logger.error(f"Error converting to lamports: {amount}")
        raise ValueError(f"Неверное количество токенов: {str(e)}")

def from_lamports(lamports: int, decimals: int = 9) -> float:
    """
    Конвертация из минимальных единиц в токены
    
    Args:
        lamports: Количество в минимальных единицах
        decimals: Количество десятичных знаков токена (9 для SOL)
        
    Returns:
        float: Количество токенов
        
    Raises:
        ValueError: Если передано некорректное значение
    """
    try:
        if lamports < 0:
            raise ValueError("Количество lamports должно быть положительным")
            
        # Конвертируем в токены
        amount = Decimal(lamports) / Decimal(10 ** decimals)
        
        logger.debug(f"Converted {lamports} lamports to {float(amount)} tokens (decimals={decimals})")
        return float(amount)
        
    except (ValueError, decimal.InvalidOperation) as e:
        logger.error(f"Error converting from lamports: {lamports}")
        raise ValueError(f"Неверное количество lamports: {str(e)}")

def format_token_amount(amount: Union[float, Decimal], decimals: int = 9) -> str:
    """
    Форматирование количества токенов с учетом значимых цифр
    
    Args:
        amount: Количество токенов
        decimals: Количество десятичных знаков токена
        
    Returns:
        str: Отформатированное количество
    """
    try:
        value = Decimal(str(amount))
        
        # Определяем формат в зависимости от величины
        if value >= 1:
            # Для больших чисел показываем 2 знака после запятой
            return f"{value:.2f}"
        else:
            # Для малых чисел показываем больше знаков, но не больше decimals
            return f"{value:.{min(6, decimals)}f}".rstrip('0').rstrip('.')
            
    except (ValueError, decimal.InvalidOperation):
        return str(amount)

def log_transaction(
    user_id: int,
    tx_type: TransactionType,
    token: str,
    amount: Union[float, Decimal],
    status: str,
    tx_signature: Optional[str] = None,
    error: Optional[str] = None
) -> None:
    """
    Логирование транзакции
    
    Args:
        user_id: Telegram ID пользователя
        tx_type: Тип транзакции (buy/sell/withdraw)
        token: Название или адрес токена
        amount: Количество токенов
        status: Статус транзакции (success/error)
        tx_signature: Подпись транзакции в Solana (опционально)
        error: Описание ошибки если статус error (опционально)
    """
    try:
        # Форматируем сумму
        formatted_amount = format_token_amount(amount)
        
        # Формируем базовое сообщение
        message = (
            f"User: {user_id} | "
            f"Type: {tx_type} | "
            f"Token: {token} | "
            f"Amount: {formatted_amount} | "
            f"Status: {status}"
        )
        
        # Добавляем ссылку на транзакцию если есть
        if tx_signature:
            message += f" | TX: https://solscan.io/tx/{tx_signature}"
            
        # Добавляем описание ошибки если есть
        if error:
            message += f" | Error: {error}"
            
        # Логируем с специальным маркером для фильтрации
        logger.bind(transaction=True).info(message)
        
    except Exception as e:
        logger.error(f"Error logging transaction: {e}") 