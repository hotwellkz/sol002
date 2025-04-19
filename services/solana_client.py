import os
import asyncio
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts
from loguru import logger
from config import SOLANA_RPC_URL

# Инициализация клиента Solana RPC
solana_client = AsyncClient(SOLANA_RPC_URL, commitment="confirmed")

async def send_transaction_with_retry(tx_bytes: bytes, max_retries: int = 3) -> str:
    """
    Отправляет транзакцию в сеть Solana с повторными попытками
    
    Args:
        tx_bytes: Байты транзакции
        max_retries: Максимальное количество попыток
        
    Returns:
        str: Подпись транзакции
        
    Raises:
        Exception: При ошибках отправки транзакции
    """
    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка {attempt + 1}/{max_retries} отправки транзакции...")
            tx_sig = await solana_client.send_raw_transaction(
                tx_bytes,
                opts=TxOpts(skip_preflight=True)
            )
            logger.info(f"✅ Транзакция успешно отправлена: {tx_sig}")
            
            # Извлекаем сигнатуру из ответа, если это словарь
            if isinstance(tx_sig, dict) and 'result' in tx_sig:
                tx_sig = tx_sig['result']
                
            return tx_sig
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ошибка при отправке транзакции: {error_msg}")
            
            if "429" in error_msg:  # Rate limit
                wait_time = 2 * (attempt + 1)
                logger.warning(f"Rate limit достигнут, ожидание {wait_time} секунд...")
                await asyncio.sleep(wait_time)
                continue
                
            if attempt == max_retries - 1:
                raise Exception(f"❌ Не удалось отправить транзакцию после {max_retries} попыток")
                
            await asyncio.sleep(1)
            
async def confirm_transaction_with_retry(tx_sig: str, max_retries: int = 3) -> bool:
    """
    Подтверждает транзакцию в сети Solana с повторными попытками
    
    Args:
        tx_sig: Подпись транзакции
        max_retries: Максимальное количество попыток
        
    Returns:
        bool: True если транзакция подтверждена, иначе False
        
    Raises:
        Exception: При ошибках подтверждения транзакции
    """
    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка {attempt + 1}/{max_retries} подтверждения транзакции...")
            
            # Если tx_sig - словарь, извлекаем result
            if isinstance(tx_sig, dict) and 'result' in tx_sig:
                tx_sig = tx_sig['result']
                
            response = await solana_client.confirm_transaction(tx_sig)
            
            if response and 'result' in response:
                value = response['result'].get('value', False)
                if value:
                    logger.info(f"✅ Транзакция подтверждена: {tx_sig}")
                    return True
            
            logger.warning(f"Транзакция не подтверждена, попытка {attempt + 1}/{max_retries}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
                
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при подтверждении транзакции: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            raise Exception(f"❌ Не удалось подтвердить транзакцию после {max_retries} попыток") 