import aiohttp
import base58
import base64
import asyncio
import os
from solana.rpc.async_api import AsyncClient
from solana.keypair import Keypair
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from loguru import logger
from typing import Dict, Any, Optional, Union
from solders.rpc.responses import SendTransactionResp
from solana.rpc.commitment import Commitment
from solders.signature import Signature
from services.utils import decrypt_private_key
from services.solana_client import solana_client, send_transaction_with_retry, confirm_transaction_with_retry
import requests
import httpx
from solana.exceptions import SolanaRpcException
from solana.publickey import PublicKey
from config import (
    SOLANA_RPC_URL,
    JUPITER_API_URL,
    JUPITER_API_KEY,
    JUPITER_PLATFORM_FEE_BPS,
    JUPITER_PLATFORM_FEE_ACCOUNT,
    SOLANA_TOKEN_ADDRESSES
)

class JupiterService:
    """
    Сервис для взаимодействия с Jupiter API для совершения операций обмена токенов Solana.
    Поддерживает следующие операции:
    - Покупка токенов за SOL (SOL → Токен)
    - Продажа токенов за SOL (Токен → SOL)
    - Получение котировок и оптимальных маршрутов обмена
    """
    def __init__(self):
        self.quote_api_url = f"{JUPITER_API_URL}quote"
        self.swap_api_url = f"{JUPITER_API_URL}swap"
        self.tokens_api_url = f"{JUPITER_API_URL}tokens"
        self.headers = {
            "Authorization": f"Bearer {JUPITER_API_KEY}"
        }
        # Используем единый RPC URL из конфигурации
        self.solana_client = AsyncClient(SOLANA_RPC_URL, commitment="confirmed")
        logger.info(f"Инициализирован JupiterService с API URL: {JUPITER_API_URL}")
        logger.info(f"Платформенная комиссия: {JUPITER_PLATFORM_FEE_BPS} bps ({JUPITER_PLATFORM_FEE_BPS/100}%)")
        logger.info(f"Кошелек для комиссии: {JUPITER_PLATFORM_FEE_ACCOUNT}")

    async def get_all_tokens(self) -> list:
        """
        Получить список всех поддерживаемых Jupiter токенов
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.tokens_api_url) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка получения списка токенов Jupiter: {response.status}")
                        return []
                    data = await response.json()
                    return data
        except Exception as e:
            logger.error(f"Ошибка при получении списка токенов Jupiter: {str(e)}")
            return []

    async def get_best_route(
        self, 
        input_mint: str, 
        output_mint: str, 
        amount: int, 
        slippage: float = 10.0
    ) -> Dict[str, Any]:
        """
        Получает лучший маршрут для свопа через Jupiter API
        
        Args:
            input_mint: Адрес входного токена
            output_mint: Адрес выходного токена
            amount: Количество токенов для свопа (в наименьших единицах)
            slippage: Процент проскальзывания (по умолчанию 10%)
            
        Returns:
            Dict с информацией о маршруте
            
        Raises:
            Exception: При ошибках API или невалидных параметрах
        """
        try:
            # Проверка валидности адреса токена
            try:
                # Проверяем, что это действительный адрес Solana
                PublicKey(output_mint)
            except Exception as e:
                logger.error(f"Невалидный адрес токена {output_mint}: {str(e)}")
                raise ValueError(f"Неверный формат адреса токена: {output_mint}")
                
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": str(int(slippage * 100)),
                "platformFeeBps": str(JUPITER_PLATFORM_FEE_BPS),
                "platformFeeAccount": JUPITER_PLATFORM_FEE_ACCOUNT
            }
            
            logger.debug(f"Requesting quote with params: {params}")
            
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(self.quote_api_url, params=params) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Unknown error")
                        raise Exception(f"Jupiter API error: {error_msg}")
                    
                    result = await response.json()
                    logger.debug(f"Received quote data: {result}")
                    
                    # Логируем информацию о комиссии
                    if "platformFee" in result:
                        fee_amount = result["platformFee"]["amount"]
                        logger.info(f"Платформенная комиссия: {fee_amount}")
                    
                    return result
                    
        except ValueError as ve:
            logger.error(f"Validation error: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error getting best route: {str(e)}")
            raise

    async def get_blockhash_with_retry(self, max_retries: int = 3) -> str:
        """
        Получает актуальный blockhash от Solana RPC с повторными попытками
        
        Args:
            max_retries: Максимальное количество попыток
            
        Returns:
            str: Актуальный blockhash
            
        Raises:
            Exception: При ошибках получения blockhash
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Попытка {attempt + 1}/{max_retries} получения blockhash...")
                response = await self.solana_client.get_latest_blockhash()
                
                # Для solders 0.30.2
                if hasattr(response, 'value') and hasattr(response.value, 'blockhash'):
                    recent_blockhash = str(response.value.blockhash)
                    logger.info(f"✅ Blockhash успешно получен: {recent_blockhash}")
                    return recent_blockhash
                else:
                    raise Exception("❌ Ошибка: неверный формат ответа от RPC")
                
            except Exception as e:
                logger.error(f"Ошибка при получении blockhash: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise Exception(f"❌ Не удалось получить blockhash после {max_retries} попыток")

    async def perform_swap(
        self,
        token_out_address: str,
        amount: str,
        user_wallet_address: str,
        user_private_key: str,
        slippage: float = 10.0,
        max_retries: int = 2,
        is_selling: bool = False
    ) -> str:
        """
        Выполняет своп токенов через Jupiter API.
        Поддерживает оба направления обмена: покупку и продажу токенов.
        
        Args:
            token_out_address: Адрес выходного токена при покупке / входного при продаже
            amount: Количество токенов для свопа (в наименьших единицах)
            user_wallet_address: Адрес кошелька пользователя
            user_private_key: Приватный ключ пользователя в формате base58
            slippage: Процент проскальзывания (по умолчанию 1%)
            max_retries: Максимальное количество попыток
            is_selling: True если это продажа токена за SOL (Токен → SOL), 
                        False если это покупка токена за SOL (SOL → Токен)
            
        Returns:
            str: Подпись транзакции
            
        Raises:
            Exception: При ошибках API или проблемах с транзакцией
        """
        # Проверка и нормализация аргументов
        if not isinstance(token_out_address, str):
            token_out_address = str(token_out_address)
        if not isinstance(amount, str):
            amount = str(amount)
        if not isinstance(user_wallet_address, str):
            user_wallet_address = str(user_wallet_address)
        if not isinstance(user_private_key, str):
            user_private_key = str(user_private_key)
            
        # Определяем входной и выходной токены в зависимости от направления обмена
        if is_selling:
            input_mint = token_out_address
            output_mint = "So11111111111111111111111111111111111111112"  # SOL
        else:
            input_mint = "So11111111111111111111111111111111111111112"  # SOL
            output_mint = token_out_address
            
        is_bonk = not is_selling and output_mint == "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        if is_bonk:
            logger.info("🦊 Обнаружен BONK токен")
            slippage = 10.0
            
        for attempt in range(max_retries):
            try:
                logger.info(f"Попытка {attempt + 1}/{max_retries} выполнения свопа")
                
                # 1. Получаем quote
                quote_data = await self._get_quote(
                    input_mint=input_mint,
                    output_mint=output_mint,
                    amount=amount,
                    slippage=slippage
                )
                
                if not quote_data:
                    logger.error("Не удалось получить quote от Jupiter API")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    raise Exception("Не удалось получить quote от Jupiter API")
                
                # 2. Выполняем своп
                swap_transaction = await self._get_swap_transaction(
                    user_wallet_address=user_wallet_address,
                    quote_data=quote_data
                )
                
                if not swap_transaction:
                    logger.error("Не удалось получить транзакцию свопа от Jupiter API")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    raise Exception("Не удалось получить транзакцию свопа от Jupiter API")
                
                # 3. Отправляем транзакцию
                signature = await self._send_swap_transaction(
                    swap_transaction=swap_transaction,
                    user_private_key=user_private_key
                )
                
                if not signature:
                    logger.error("Не удалось отправить транзакцию свопа")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    raise Exception("Не удалось отправить транзакцию свопа")
                
                # Все прошло успешно, возвращаем signature
                return signature
                        
            except Exception as e:
                logger.error(f"Ошибка при выполнении свопа: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise
                
    async def _get_quote(self, input_mint: str, output_mint: str, amount: str, slippage: float) -> dict:
        """Получает quote от Jupiter API"""
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self.headers) as client:
                quote_params = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount,
                    "slippageBps": str(int(slippage * 100)),
                    "onlyDirectRoutes": "true",
                    "platformFeeBps": str(JUPITER_PLATFORM_FEE_BPS),
                    "platformFeeAccount": JUPITER_PLATFORM_FEE_ACCOUNT
                }
                
                logger.debug(f"Отправка запроса quote с параметрами: {quote_params}")
                
                quote_response = await client.get(
                    self.quote_api_url,
                    params=quote_params
                )
                
                if quote_response.status_code != 200:
                    error_data = quote_response.json()
                    error_msg = error_data.get("error", "Unknown error")
                    raise Exception(f"Jupiter Quote API error: {error_msg}")
                
                quote_data = quote_response.json()
                if "error" in quote_data:
                    raise Exception(f"Jupiter Quote API error: {quote_data['error']}")
                
                # Логируем информацию о комиссии
                if "platformFee" in quote_data:
                    fee_amount = quote_data["platformFee"]["amount"]
                    logger.info(f"Платформенная комиссия: {fee_amount}")
                
                logger.info(f"Получен quote")
                return quote_data
                
        except Exception as e:
            logger.error(f"Ошибка при получении quote: {str(e)}")
            return None
    
    async def _get_swap_transaction(self, user_wallet_address: str, quote_data: dict) -> str:
        """Получает транзакцию свопа от Jupiter API"""
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self.headers) as client:
                # Готовим запрос на свап
                swap_req = {
                    "userPublicKey": user_wallet_address,  # строка, не функция
                    "wrapUnwrapSOL": True,
                    "quoteResponse": quote_data,
                    "asLegacyTransaction": True,
                    "platformFeeBps": JUPITER_PLATFORM_FEE_BPS,
                    "platformFeeAccount": JUPITER_PLATFORM_FEE_ACCOUNT
                }

                logger.debug("Отправка запроса swap")
                
                resp = await client.post(self.swap_api_url, json=swap_req)
                
                # Проверка корректности ответа
                if resp.status_code != 200:
                    try:
                        error_data = resp.json()
                        error_msg = error_data.get("error", "Unknown error")
                    except Exception as json_err:
                        # Если ответ не является JSON, выведем его содержимое
                        error_text = resp.text
                        logger.error(f"Некорректный ответ API (не JSON): {error_text[:200]}")
                        error_msg = f"Неожиданный ответ от API: {str(json_err)}"
                    raise Exception(f"Jupiter Swap API error: {error_msg}")
                
                # Получение и валидация данных ответа
                swap_data = resp.json()
                logger.info("✅ Swap запрос успешно обработан")
                
                if "error" in swap_data:
                    raise Exception(f"Jupiter Swap API error: {swap_data['error']}")
                
                # Проверка наличия транзакции в ответе
                tx_b64 = swap_data.get("swapTransaction")
                if not tx_b64 or len(tx_b64) < 100:
                    logger.warning("Получена пустая транзакция")
                    return None
                
                return tx_b64
                
        except Exception as e:
            logger.error(f"Ошибка при получении транзакции свопа: {str(e)}")
            return None
    
    async def _send_swap_transaction(self, swap_transaction: str, user_private_key: str) -> str:
        """Отправляет транзакцию свопа в сеть Solana"""
        try:
            # Декодируем транзакцию из base64
            try:
                tx_bytes = base64.b64decode(swap_transaction)
                
                # Создаем объект транзакции
                tx = Transaction.deserialize(tx_bytes)
            except Exception as decode_err:
                logger.error(f"Ошибка при декодировании транзакции: {str(decode_err)}")
                logger.error(f"Начало строки транзакции: {swap_transaction[:50]}")
                raise Exception(f"Невозможно декодировать транзакцию: {str(decode_err)}")
            
            # Расшифровываем приватный ключ и создаем кошелек
            try:
                # Пробуем расшифровать ключ, так как после обновления он может быть зашифрован
                decrypted_key = decrypt_private_key(user_private_key)
                logger.debug("Приватный ключ успешно расшифрован")
            except Exception as decrypt_err:
                # Если расшифровка не удалась, возможно ключ не зашифрован (старый формат)
                logger.info(f"Не удалось расшифровать ключ, используем как есть: {str(decrypt_err)}")
                decrypted_key = user_private_key
                
            # Создаем кошелек из расшифрованного приватного ключа
            private_key_bytes = base58.b58decode(decrypted_key)
            wallet = Keypair.from_secret_key(private_key_bytes)
            
            # Подписываем транзакцию
            tx.sign(wallet)
            
            # Отправляем транзакцию в сеть
            tx_sig = await self.solana_client.send_raw_transaction(
                tx.serialize(),
                opts=TxOpts(
                    skip_preflight=True,
                    preflight_commitment="confirmed",
                    max_retries=3
                )
            )
            
            # Получаем signature
            if isinstance(tx_sig, str):
                signature = tx_sig
            else:
                signature = str(tx_sig.value) if hasattr(tx_sig, 'value') else str(tx_sig)
                
            logger.info(f"✅ Транзакция отправлена: {signature}")
            logger.info(f"💰 Комиссия ({JUPITER_PLATFORM_FEE_BPS/100}%) будет отправлена на: {JUPITER_PLATFORM_FEE_ACCOUNT}")
            
            # Ждем подтверждения транзакции
            try:
                # Даем время на подтверждение
                await asyncio.sleep(2)
                
                # Проверяем статус транзакции
                status = await self.solana_client.get_signature_statuses([signature])
                
                if status and hasattr(status, 'value') and status.value and status.value[0]:
                    tx_status = status.value[0]
                    if hasattr(tx_status, 'err') and tx_status.err:
                        logger.error(f"❌ Транзакция завершилась с ошибкой: {tx_status.err}")
                        raise Exception(f"Transaction failed: {tx_status.err}")
                    elif hasattr(tx_status, 'confirmation_status') and str(tx_status.confirmation_status) in ["confirmed", "finalized"]:
                        logger.info(f"✅ Swap confirmed! Transaction: {signature}")
                    else:
                        logger.warning(f"⚠️ Транзакция в процессе подтверждения")
                else:
                    logger.warning(f"⚠️ Не удалось получить статус транзакции: {signature}")
                    
            except Exception as confirm_error:
                logger.error(f"Ошибка при подтверждении транзакции: {str(confirm_error)}")
                # Не вызываем raise - лучше вернуть сигнатуру, даже если не удалось подтвердить
            
            return signature
            
        except Exception as e:
            logger.error(f"Ошибка при отправке транзакции: {str(e)}")
            return None

    async def execute_swap(
        self, 
        user_pubkey: str, 
        user_privkey: str, 
        route: Dict[str, Any]
    ) -> str:
        """
        Выполняет своп через Jupiter API
        
        Args:
            user_pubkey: Публичный ключ пользователя
            user_privkey: Приватный ключ пользователя в формате base58
            route: Маршрут свопа, полученный из get_best_route
            
        Returns:
            str: Ссылка на транзакцию в Solscan или сообщение об ошибке
            
        Raises:
            Exception: При ошибках API или проблемах с транзакцией
        """
        try:
            logger.info("Начало выполнения свопа...")
            
            # Извлекаем параметры из route
            output_mint = route.get("outputMint")
            amount = route.get("inAmount")
            
            if not all([output_mint, amount]):
                raise ValueError("❌ Неверный формат route: отсутствуют необходимые параметры")
            
            logger.info(f"Параметры свопа: output_mint={output_mint}, amount={amount}")
            
            # Устанавливаем проскальзывание в зависимости от токена
            if output_mint == "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263":  # BONK
                # Уменьшаем проскальзывание для BONK, сохраняя эффективность
                bonk_slippage = 10.0
                logger.info(f"Установлено проскальзывание для BONK: {bonk_slippage}%")
            else:
                # Стандартное проскальзывание для других токенов
                bonk_slippage = 1.0
            
            # Выполняем своп через новую функцию
            signature = await self.perform_swap(
                token_out_address=output_mint,
                amount=str(amount),
                user_wallet_address=user_pubkey,
                user_private_key=user_privkey,
                slippage=bonk_slippage,  # Используем установленное проскальзывание
                is_selling=False  # Покупка токена за SOL
            )
            
            # Извлекаем signature из строкового представления ответа
            if isinstance(signature, str):
                if 'Signature(' in signature:
                    tx_signature = signature.split('Signature(')[1].split(')')[0]
                else:
                    tx_signature = signature
            else:
                tx_signature = str(signature)
            
            # Формируем и возвращаем ссылку на транзакцию
            solscan_url = f"https://solscan.io/tx/{tx_signature}"
            logger.info(f"Своп отправлен успешно: {solscan_url}")
            
            # Пробуем подтвердить транзакцию
            try:
                # Ждем немного для подтверждения
                await asyncio.sleep(2)
                
                # Проверяем статус транзакции
                status_resp = await self.solana_client.get_signature_statuses([tx_signature])
                if 'result' in status_resp and status_resp['result'] and status_resp['result']['value']:
                    confirmation_status = status_resp['result']['value'][0]
                    if confirmation_status:
                        logger.info(f"Статус транзакции: {confirmation_status}")
                        if confirmation_status.get('err'):
                            logger.error(f"🚨 Транзакция завершилась с ошибкой: {confirmation_status.get('err')}")
                        elif confirmation_status.get('confirmationStatus') in ['finalized', 'confirmed']:
                            logger.info(f"✅ Транзакция подтверждена! ID: {tx_signature}")
                        else:
                            logger.warning(f"⏳ Транзакция в процессе подтверждения: {confirmation_status.get('confirmationStatus')}")
                    else:
                        logger.warning(f"⚠️ Транзакция не найдена в блокчейне. Возможно, еще обрабатывается или отклонена.")
            except Exception as status_error:
                logger.error(f"Ошибка при проверке статуса финальной транзакции: {status_error}")
            
            return solscan_url
            
        except Exception as e:
            logger.error(f"Ошибка в execute_swap: {str(e)}")
            
            # Анализируем ошибку для лучшего сообщения
            error_message = str(e)
            if "Custom: 1" in error_message:
                return "❌ Ошибка транзакции: Недостаточная ликвидность или слишком маленькая сумма обмена"
            elif "Custom: 6000" in error_message:
                return "❌ Ошибка транзакции: Слишком высокое проскальзывание"
            elif "0x1771" in error_message:
                return "❌ Ошибка транзакции: Недостаточно средств для выполнения обмена"
            
            return f"❌ Ошибка: {error_message}"

    async def get_token_decimals(self, token_address: str) -> int:
        """
        Получает количество decimals для токена
        
        Args:
            token_address: Адрес токена
            
        Returns:
            int: Количество decimals токена
        """
        try:
            # Формируем запрос к RPC
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenSupply",
                "params": [token_address]
            }
            
            # Отправляем запрос к RPC
            async with aiohttp.ClientSession() as session:
                async with session.post(SOLANA_RPC_URL, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка RPC при получении decimals: {response.status}")
                        return 9  # Возвращаем стандартное значение по умолчанию
                        
                    data = await response.json()
                    if "error" in data:
                        logger.error(f"Ошибка RPC при получении decimals: {data['error']}")
                        return 9
                        
                    decimals = data.get("result", {}).get("value", {}).get("decimals", 9)
                    logger.info(f"Decimals токена {token_address}: {decimals}")
                    return decimals
                    
        except Exception as e:
            logger.error(f"Ошибка при получении decimals токена: {str(e)}")
            return 9  # Возвращаем стандартное значение по умолчанию

    async def execute_sell(
        self, 
        user_pubkey: str, 
        user_privkey: str, 
        token_address: str,
        amount: Union[int, float, str]
    ) -> str:
        """
        Выполняет продажу токена за SOL через Jupiter API
        
        Args:
            user_pubkey: Публичный ключ пользователя (должен быть строкой base58)
            user_privkey: Приватный ключ пользователя в формате base58
            token_address: Адрес токена или его символ (например, 'RAY' или 'Orca')
            amount: Количество токенов для продажи (может быть int, float или str)
            
        Returns:
            str: Ссылка на транзакцию в Solscan или сообщение об ошибке
        """
        try:
            # Логируем и проверяем user_pubkey
            logger.debug(f"user_pubkey={user_pubkey} ({type(user_pubkey)})")
            
            # Проверяем тип и конвертируем в строку если нужно
            if not isinstance(user_pubkey, str):
                try:
                    user_pubkey = str(user_pubkey)
                    logger.warning(f"user_pubkey был автоматически конвертирован в строку из {type(user_pubkey)}")
                except Exception as e:
                    error_msg = f"Не удалось конвертировать user_pubkey в строку: {str(e)}"
                    logger.error(error_msg)
                    return f"❌ Ошибка: {error_msg}"
            
            # Очищаем от пробелов
            user_pubkey = user_pubkey.strip()
            
            # Проверяем длину
            if len(user_pubkey) < 32:
                error_msg = f"Слишком короткий адрес кошелька: {user_pubkey}"
                logger.error(error_msg)
                return f"❌ Ошибка: {error_msg}"
                
            # Проверяем формат base58
            try:
                decoded = base58.b58decode(user_pubkey)
                if len(decoded) != 32:
                    error_msg = f"Неверная длина декодированного адреса кошелька: {len(decoded)} байт (должно быть 32)"
                    logger.error(error_msg)
                    return f"❌ Ошибка: {error_msg}"
            except Exception as e:
                error_msg = f"Адрес кошелька не в формате base58: {str(e)}"
                logger.error(error_msg)
                return f"❌ Ошибка: {error_msg}"
                
            # Проверяем через PublicKey
            try:
                wallet_pubkey = PublicKey(user_pubkey)
                logger.info(f"✅ Адрес кошелька валиден: {wallet_pubkey}")
            except Exception as e:
                error_msg = f"Невалидный адрес кошелька: {str(e)}"
                logger.error(error_msg)
                return f"❌ Ошибка: {error_msg}"

            logger.info(f"Начало продажи токена {token_address}")
            
            # Конвертируем символ токена в адрес, если это символ
            original_input = token_address
            if token_address.upper() in SOLANA_TOKEN_ADDRESSES:
                token_address = SOLANA_TOKEN_ADDRESSES[token_address.upper()]
                logger.info(f"Конвертирован символ токена {original_input} в адрес: {token_address}")
            
            # Проверяем валидность адреса токена
            try:
                token_pubkey = PublicKey(token_address)
            except Exception as e:
                error_msg = f"Невалидный адрес токена {original_input}: {str(e)}"
                logger.error(error_msg)
                return f"❌ Ошибка: {error_msg}"
            
            # Получаем баланс токена и его decimals
            token_balance_raw, token_decimals = await self.get_token_balance(str(wallet_pubkey), str(token_pubkey))
            if not token_balance_raw:
                return f"❌ Ошибка: Не удалось получить баланс токена {original_input}"
                
            logger.info(f"Decimals токена {original_input} ({token_pubkey}): {token_decimals}")
            
            # Конвертируем amount в raw_amount
            try:
                # Если amount уже целое число, используем его как есть
                if isinstance(amount, int):
                    raw_amount = amount
                # Если amount строка, пробуем преобразовать в float
                elif isinstance(amount, str):
                    amount_float = float(amount)
                    raw_amount = int(amount_float * (10 ** token_decimals))
                # Если amount float, умножаем на 10^decimals
                elif isinstance(amount, float):
                    raw_amount = int(amount * (10 ** token_decimals))
                else:
                    raise ValueError(f"Неверный тип amount: {type(amount)}")
                    
                logger.info(f"Конвертированный amount: {raw_amount} (из {amount} * 10^{token_decimals})")
                
                # Проверяем, что raw_amount не слишком большой
                if raw_amount > 10**18:  # Максимально разумное значение
                    raise ValueError(f"Сумма слишком большая: {raw_amount}")
                    
            except (ValueError, TypeError) as e:
                logger.error(f"Ошибка при конвертации amount: {str(e)}")
                return f"❌ Ошибка: Неверный формат суммы: {str(e)}"
            
            # Конвертируем баланс в человекочитаемый формат для логирования
            token_balance = token_balance_raw / (10 ** token_decimals)
            logger.info(f"Баланс токена {original_input}: {token_balance:.6f} (raw: {token_balance_raw})")
            
            # Проверяем, что запрошенная сумма не превышает баланс
            if raw_amount > token_balance_raw:
                # Конвертируем оба значения в человекочитаемый формат для сообщения
                human_balance = token_balance_raw / (10 ** token_decimals)
                human_amount = raw_amount / (10 ** token_decimals)
                return f"❌ Ошибка: Недостаточно токенов. Баланс: {human_balance:.6f}, Запрошено: {human_amount:.6f}"
            
            # Округляем сумму вниз до допустимого значения
            # Оставляем 0.01 токена на комиссию
            min_balance = int(0.01 * (10 ** token_decimals))
            if token_balance_raw - raw_amount < min_balance:
                raw_amount = token_balance_raw - min_balance
                human_amount = raw_amount / (10 ** token_decimals)
                logger.info(f"Сумма скорректирована до: {human_amount:.6f} (оставлено {min_balance/(10**token_decimals):.6f} на комиссию)")
            
            # SOL всегда будет выходным токеном при продаже
            output_mint = "So11111111111111111111111111111111111111112"  # SOL
            
            # Устанавливаем базовое проскальзывание
            slippage = 1.0  # Уменьшаем проскальзывание для ускорения
            
            # Для некоторых токенов с низкой ликвидностью увеличиваем проскальзывание
            if token_address not in ["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 
                                     "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"]:
                slippage = 3.0  # Более разумное значение для других токенов
            
            # Получаем маршрут и сразу выполняем своп
            try:
                # Получаем маршрут для свопа
                route = await self.get_best_route(
                    input_mint=str(token_address),  # Убедимся, что это строка
                    output_mint=output_mint,
                    amount=str(raw_amount),  # Убедимся, что это строка
                    slippage=slippage
                )
            
                if not route:
                    return f"❌ Ошибка: Не удалось найти маршрут для продажи токена {original_input}"
                
                # Проверяем наличие routePlan
                if 'routePlan' not in route or not route.get('routePlan'):
                    logger.error("❌ Ошибка: routePlan пустой или отсутствует")
                    return f"❌ Ошибка: Не удалось найти маршрут для продажи токена {original_input}"
                
                # Сразу выполняем своп
                signature = await self.perform_swap(
                    token_out_address=str(token_address),  # Убедимся, что это строка
                    amount=str(raw_amount),  # Убедимся, что это строка
                    user_wallet_address=str(user_pubkey),  # Убедимся, что это строка
                    user_private_key=str(user_privkey),  # Убедимся, что это строка
                    slippage=slippage,
                    is_selling=True
                )
                
                # Извлекаем signature из строкового представления ответа
                if not signature:
                    logger.error("❌ Ошибка: Не удалось получить signature транзакции")
                    return "❌ Ошибка: Не удалось получить signature транзакции"
                
                # Формируем и возвращаем ссылку на транзакцию
                if isinstance(signature, str):
                    # Если signature уже строка, используем как есть
                    tx_signature = signature
                else:
                    try:
                        # Безопасное приведение к строке
                        tx_signature = str(signature)
                        # Если это объект Signature, извлекаем строковое представление
                        if 'Signature(' in tx_signature:
                            tx_signature = tx_signature.split('Signature(')[1].split(')')[0]
                    except Exception as e:
                        logger.error(f"❌ Ошибка при обработке signature: {str(e)}")
                        return "❌ Ошибка: Неверный формат signature транзакции"
                    
                solscan_url = f"https://solscan.io/tx/{tx_signature}"
                logger.info(f"Продажа токена {original_input} отправлена: {solscan_url}")
                return solscan_url
                
            except Exception as e:
                logger.error(f"Ошибка при продаже токена {original_input}: {str(e)}")
                error_msg = str(e)
                
                # Более дружелюбные сообщения об ошибках
                if "insufficient funds" in error_msg.lower() or "not enough lamports" in error_msg.lower():
                    return "❌ Ошибка: Недостаточно средств для выполнения операции"
                elif "invalid token" in error_msg.lower() or "invalid mint" in error_msg.lower():
                    return "❌ Ошибка: Неверный адрес токена"
                elif "slippage exceeded" in error_msg.lower():
                    return "❌ Ошибка: Превышен порог проскальзывания. Попробуйте еще раз"
                elif "liquidity" in error_msg.lower():
                    return "❌ Ошибка: Недостаточная ликвидность для продажи. Попробуйте уменьшить сумму"
                elif "Custom: 1" in error_msg:
                    return "❌ Ошибка: Недостаточная ликвидность в пуле для продажи токена"
                
                return f"❌ Ошибка при продаже токена {original_input}: {error_msg}"
                
        except Exception as e:
            logger.error(f"Ошибка в execute_sell: {str(e)}")
            return f"❌ Ошибка: {str(e)}"
            
    async def get_token_balance(self, wallet_address: str, token_address: str) -> tuple[int, int]:
        """
        Получает баланс токена и его decimals для указанного кошелька
        
        Args:
            wallet_address: Адрес кошелька
            token_address: Адрес токена или его символ (например, 'RAY' или 'Orca')
            
        Returns:
            tuple[int, int]: (баланс токена в наименьших единицах, количество decimals)
        """
        try:
            original_input = token_address
            # Проверяем, передан ли символ токена вместо адреса
            if token_address.upper() in SOLANA_TOKEN_ADDRESSES:
                token_address = SOLANA_TOKEN_ADDRESSES[token_address.upper()]
                logger.info(f"Конвертирован символ токена {original_input} в адрес: {token_address}")

            # Проверяем валидность адресов
            try:
                # Очищаем адреса от возможных спецсимволов
                wallet_address = wallet_address.strip()
                token_address = token_address.strip()
                
                # Создаем объекты PublicKey для проверки валидности
                try:
                    token_pubkey = PublicKey(token_address)
                except Exception as e:
                    logger.error(f"Невалидный адрес токена {original_input}: {str(e)}")
                    return 0, 9
                    
                try:
                    wallet_pubkey = PublicKey(wallet_address)
                except Exception as e:
                    logger.error(f"Невалидный адрес кошелька: {str(e)}")
                    return 0, 9
                    
            except Exception as e:
                logger.error(f"Ошибка при проверке адресов: {str(e)}")
                return 0, 9

            # Формируем запрос к RPC для получения decimals
            decimals_payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getTokenSupply",
                "params": [str(token_pubkey)]
            }
            
            # Формируем запрос к RPC для получения баланса
            balance_payload = {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "getTokenAccountsByOwner",
                "params": [
                    str(wallet_pubkey),
                    {
                        "mint": str(token_pubkey)
                    },
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }
            
            logger.info(f"Запрашиваем информацию для токена {original_input} ({token_address})")
            
            # Отправляем запросы к RPC
            async with aiohttp.ClientSession() as session:
                # Получаем decimals
                async with session.post(SOLANA_RPC_URL, json=decimals_payload) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка RPC при получении decimals: {response.status}")
                        return 0, 9
                        
                    decimals_data = await response.json()
                    if "error" in decimals_data:
                        logger.error(f"Ошибка RPC при получении decimals: {decimals_data['error']}")
                        return 0, 9
                        
                    decimals = decimals_data.get("result", {}).get("value", {}).get("decimals", 9)
                    logger.info(f"Decimals токена {original_input}: {decimals}")
                
                # Получаем баланс
                async with session.post(SOLANA_RPC_URL, json=balance_payload) as response:
                    if response.status != 200:
                        logger.error(f"Ошибка RPC при получении баланса: {response.status}")
                        return 0, decimals
                        
                    data = await response.json()
                    if "error" in data:
                        logger.error(f"Ошибка RPC при получении баланса: {data['error']}")
                        return 0, decimals
                        
                    value = data.get("result", {}).get("value", [])
                    if not value:
                        logger.warning(f"Токен-аккаунт не найден для {original_input}")
                        return 0, decimals
                        
                    # Получаем данные аккаунта
                    try:
                        account_data = value[0]["account"]["data"]
                        
                        # Проверяем тип данных
                        if isinstance(account_data, str):
                            # Если данные в виде строки (возможно base64), логируем и возвращаем 0
                            logger.warning(f"Данные аккаунта в формате строки для {original_input}")
                            return 0, decimals
                        elif isinstance(account_data, dict):
                            # Если данные в формате jsonParsed
                            parsed_data = account_data.get("parsed", {})
                            if not parsed_data or "info" not in parsed_data:
                                logger.warning(f"Неверный формат данных аккаунта для {original_input}")
                                return 0, decimals
                                
                            token_info = parsed_data["info"]
                            if "tokenAmount" not in token_info:
                                logger.warning(f"Неверный формат данных баланса для {original_input}")
                                return 0, decimals
                                
                            balance = int(token_info["tokenAmount"]["amount"])
                            logger.info(f"Баланс токена {original_input}: {balance}")
                            return balance, decimals
                        else:
                            logger.warning(f"Неизвестный формат данных аккаунта для {original_input}")
                            return 0, decimals
                    except (IndexError, KeyError) as e:
                        logger.error(f"Ошибка при обработке данных аккаунта: {str(e)}")
                        return 0, decimals
                    
        except Exception as e:
            logger.error(f"Ошибка при получении баланса токена {original_input}: {str(e)}")
            return 0, 9  # Возвращаем 0 как баланс и 9 как стандартное значение decimals 