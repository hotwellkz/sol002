# Стандартные библиотеки
import json
import logging
import traceback
import base58
from datetime import datetime
from typing import Dict, List, Optional, Union, Any

# Solana библиотеки
from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey
from solana.keypair import Keypair
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.rpc import types
from solana.rpc.types import TokenAccountOpts

# SPL Token библиотеки
from spl.token.instructions import get_associated_token_address

# Внутренние импорты
from loguru import logger
from config import SOLANA_RPC_URL, WALLET_PRIVATE_KEY, SOLANA_TOKEN_ADDRESSES
from services.wallet import WalletService

class SolanaService:
    def __init__(self):
        self.client = AsyncClient(SOLANA_RPC_URL)
        self.wallet_service = WalletService()
        logger.info("Solana service initialized")

    async def get_wallet_tokens(self, public_key: str) -> dict:
        print("=== TEST PRINT ===")
        logger.error("=== TEST LOGGER ===")
        """
        Возвращает словарь {mint_address: balance} всех токенов с ненулевым балансом на кошельке пользователя.
        """
        from solana.rpc.types import TokenAccountOpts
        from solana.publickey import PublicKey
        tokens = {}
        try:
            owner_pubkey = PublicKey(public_key) if not isinstance(public_key, PublicKey) else public_key
            program_id = PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
            resp = await self.client.get_token_accounts_by_owner(
                owner_pubkey,
                TokenAccountOpts(program_id=program_id)
            )
            value = resp.value  # это список объектов
            logger.info(f"[get_wallet_tokens] Всего токен-аккаунтов: {len(value)}")
            logger.debug(f"[get_wallet_tokens] Ответ Solana: {value}")
            for token_account in value:
                logger.debug(f"[DIAG: account type={type(token_account)}, dir={dir(token_account)}]")
                account = getattr(token_account, 'account', None)
                pubkey = getattr(token_account, 'pubkey', None)
                if account is None:
                    logger.error("[get_wallet_tokens] Нет account в token_account!")
                    continue
                data = getattr(account, 'data', None)
                raw_data = None
                if isinstance(data, tuple) and len(data) > 0:
                    # Старый вариант: (base64, encoding)
                    import base64
                    raw_data = base64.b64decode(data[0])
                elif isinstance(data, str):
                    # Новый вариант: hex-строка
                    raw_data = bytes.fromhex(data)
                elif isinstance(data, bytes):
                    raw_data = data
                elif hasattr(data, 'data') and isinstance(data.data, str):
                    # data - объект с атрибутом .data (hex-строка)
                    raw_data = bytes.fromhex(data.data)
                logger.debug(f"[get_wallet_tokens] Тип data: {type(raw_data)}, содержимое: {raw_data}")
                logger.error(f"[DIAG: raw_data type={type(raw_data)}, len={len(raw_data) if isinstance(raw_data, bytes) else 'N/A'}]")
                if isinstance(raw_data, bytes) and len(raw_data) >= 64:
                    logger.error("[DIAG: valid raw_data, proceed to decode]")
                    try:
                        mint = PublicKey(raw_data[0x0:0x20]).to_base58().decode()
                        amount_bytes = raw_data[0x40:0x48]
                        amount = int.from_bytes(amount_bytes, 'little')
                        logger.debug(f"[DIAG: amount_bytes={amount_bytes.hex()}, amount={amount}]")
                        logger.error(f"[DIAG: pubkey={pubkey}, mint={mint}, amount={amount}]")
                        if amount > 0:
                            tokens[mint] = {"amount": amount, "pubkey": str(pubkey)}
                    except Exception as e:
                        logger.error(f"[DIAG: exception: {e}]")
                else:
                    logger.error("[DIAG: raw_data is not valid bytes or too short]")
            return tokens
        except Exception as e:
            logger.error(f"Ошибка при получении токенов пользователя: {e}")
            return {}

    async def get_balance(self):
        """Получение баланса кошелька"""
        try:
            wallet_info = await self.wallet_service.get_wallet_info()
            return {
                'sol': wallet_info['balance'],
                'usdc': 0,  # TODO: Реализовать проверку баланса USDC
                'spl_tokens': []  # TODO: Реализовать проверку баланса SPL токенов
            }
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            raise

    async def send_transaction(self, to_address: str, amount: float):
        """Отправка транзакции"""
        try:
            transaction = Transaction()
            transaction.add(
                transfer(
                    TransferParams(
                        from_pubkey=self.wallet_service.keypair.public_key,
                        to_pubkey=to_address,
                        lamports=int(amount * 1e9)  # Конвертация SOL в lamports
                    )
                )
            )
            result = await self.client.send_transaction(transaction, self.wallet_service.keypair)
            return result['result']
        except Exception as e:
            logger.error(f"Error sending transaction: {e}")
            raise

    async def get_sol_balance(self, public_key: str) -> float:
        """
        Получение баланса SOL
        
        Args:
            public_key: Публичный ключ кошелька
            
        Returns:
            float: Баланс в SOL
        """
        try:
            logger.info(f"Getting SOL balance for {public_key}")
            response = await self.client.get_balance(PublicKey(public_key))
            logger.info(f"SOL balance response: {response}")
            
            if not response:
                logger.warning(f"Empty response for SOL balance: {response}")
                return 0.0
                
            try:
                # Пробуем получить значение как атрибут
                if hasattr(response, 'value'):
                    balance = int(response.value)
                # Если не получилось, пробуем как словарь
                elif isinstance(response, dict) and 'result' in response:
                    balance = int(response['result']['value'])
                else:
                    logger.error(f"Unexpected response format for SOL balance: {response}")
                    return 0.0
                    
                final_balance = balance / 1e9  # Конвертация lamports в SOL
                logger.info(f"Calculated SOL balance: {final_balance}")
                return round(final_balance, 2)
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                logger.error(f"Error parsing SOL balance for {public_key}: {e}, response: {response}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting SOL balance for {public_key}: {e}")
            return 0.0

    async def get_token_balance(self, public_key: str, token_mint: str) -> float:
        """
        Получение баланса SPL токена
        
        Args:
            public_key: Публичный ключ кошелька
            token_mint: Адрес токена
            
        Returns:
            float: Баланс токена
        """
        try:
            # Проверка валидности аргументов
            if not public_key or not token_mint:
                logger.error(f"Invalid arguments: public_key={public_key}, token_mint={token_mint}")
                return 0.0
            
            # Проверка, что это не команда или другой невалидный ввод
            if token_mint.startswith('/') or len(token_mint) < 32:
                logger.error(f"Invalid token_mint format: {token_mint}")
                return 0.0
                
            try:
                # Преобразуем адреса в PublicKey
                owner_pubkey = PublicKey(public_key)
                token_pubkey = PublicKey(token_mint)
                
                # Получаем адрес ассоциированного токен-аккаунта
                token_account = get_associated_token_address(owner_pubkey, token_pubkey)
                logger.info(f"Getting balance for token {token_mint} at account {token_account}")
                
                # Проверяем существование токен-аккаунта
                account_info = await self.client.get_account_info(token_account)
                if not account_info or not account_info.value:
                    logger.info(f"Token account {token_account} does not exist")
                    return 0.0
                
                # Получаем баланс
                response = await self.client.get_token_account_balance(token_account)
                logger.info(f"Token balance response: {response}")
                
                if not response:
                    logger.warning(f"Empty response for token {token_mint}")
                    return 0.0
                
                # Извлекаем значения из ответа
                try:
                    # Пробуем получить значение как атрибут
                    if hasattr(response, 'value'):
                        result = response.value
                    # Если не получилось, пробуем как словарь
                    elif isinstance(response, dict) and 'result' in response:
                        result = response['result']
                    else:
                        logger.error(f"Unexpected response format for token {token_mint}: {response}")
                        return 0.0
                        
                    # Получаем значения amount и decimals
                    if isinstance(result, dict):
                        amount = result.get('amount', '0')
                        decimals = result.get('decimals', 0)
                    else:
                        amount = getattr(result, 'amount', '0')
                        decimals = getattr(result, 'decimals', 0)
                    
                    logger.info(f"Token {token_mint} amount: {amount}, decimals: {decimals}")
                    
                    # Вычисляем баланс
                    balance = float(amount) / (10 ** int(decimals))
                    logger.info(f"Calculated balance for token {token_mint}: {balance}")
                    return round(balance, 2)
                except (KeyError, ValueError, TypeError, AttributeError) as e:
                    logger.error(f"Error parsing balance for {token_mint}: {e}, response: {response}")
                    return 0.0
            except Exception as e:
                logger.error(f"Error getting token balance for {token_mint}: {e}")
                return 0.0
        except Exception as e:
            logger.error(f"Error getting token balance for {public_key}: {e}")
            return 0.0

    async def get_all_balances(self, public_key: str) -> Dict[str, float]:
        """
        Получение балансов только тех токенов, которые реально есть на кошельке (ненулевой баланс).
        Args:
            public_key: Публичный ключ кошелька
        Returns:
            Dict[str, float]: Словарь с балансами токенов
        """
        try:
            balances = {}
            # Получаем баланс SOL
            sol_balance = await self.get_sol_balance(public_key)
            if sol_balance > 0:
                balances['SOL'] = sol_balance

            # Получаем только реально существующие токены с балансом > 0
            user_tokens = await self.get_wallet_tokens(public_key)
            for mint, info in user_tokens.items():
                # Находим символ токена по mint, если есть в SOLANA_TOKEN_ADDRESSES
                token_name = None
                for name, addr in SOLANA_TOKEN_ADDRESSES.items():
                    if addr == mint:
                        token_name = name
                        break
                if not token_name:
                    token_name = mint  # если не найдено имя — используем mint
                # Получаем баланс токена (в человекочитаемом виде)
                try:
                    balance = await self.get_token_balance(public_key, mint)
                    if balance > 0:
                        balances[token_name] = balance
                except Exception as e:
                    logger.error(f"Error getting balance for {token_name}: {e}")
                    continue
            return balances
        except Exception as e:
            logger.error(f"Error getting all balances for {public_key}: {e}")
            return {'SOL': 0.0}

    def get_token_address(self, token_name: str) -> str:
        """
        Получает адрес токена по его имени
        
        Args:
            token_name: Имя токена (SOL, USDC и т.д.)
            
        Returns:
            str: Адрес токена или None если не найден
        """
        return SOLANA_TOKEN_ADDRESSES.get(token_name)
        
    async def send_sol(self, from_private_key: str, to_address: str, amount: float) -> str:
        """
        Отправка SOL на указанный адрес
        
        Args:
            from_private_key: Приватный ключ отправителя в формате base58
            to_address: Адрес получателя
            amount: Количество SOL для отправки
            
        Returns:
            str: Сигнатура транзакции
        """
        try:
            # Проверяем входные параметры
            if not from_private_key:
                raise ValueError("Приватный ключ не предоставлен")
                
            if not to_address:
                raise ValueError("Адрес получателя не предоставлен")
                
            if amount <= 0:
                raise ValueError(f"Некорректная сумма для отправки: {amount}")
                
            logger.info(f"Отправка {amount} SOL на адрес {to_address}")
            
            # Создаем keypair из приватного ключа с дополнительной обработкой ошибок
            try:
                # Пробуем декодировать как base58
                from base58 import b58decode
                private_key_bytes = None
                
                try:
                    logger.debug(f"Пробуем декодировать ключ как base58")
                    private_key_bytes = b58decode(from_private_key)
                    if len(private_key_bytes) != 64:  # Ожидаемая длина для секретного ключа Solana
                        logger.warning(f"Декодированный ключ имеет неверную длину: {len(private_key_bytes)}")
                except Exception as base58_error:
                    logger.error(f"Ошибка декодирования ключа как base58: {base58_error}")
                    
                # Если не удалось с base58, пробуем как hex
                if not private_key_bytes:
                    try:
                        logger.debug(f"Пробуем декодировать ключ как hex")
                        private_key_bytes = bytes.fromhex(from_private_key)
                        if len(private_key_bytes) != 64:
                            logger.warning(f"Декодированный hex-ключ имеет неверную длину: {len(private_key_bytes)}")
                    except Exception as hex_error:
                        logger.error(f"Ошибка декодирования ключа как hex: {hex_error}")
                
                if not private_key_bytes or len(private_key_bytes) != 64:
                    raise ValueError("Не удалось создать корректный ключ нужной длины (64 байта)")
                
                # Создаем keypair
                keypair = Keypair.from_secret_key(private_key_bytes)
                from_pubkey = keypair.public_key
                logger.info(f"Успешно создан keypair. Публичный ключ: {from_pubkey}")
                
            except Exception as keypair_error:
                logger.error(f"Ошибка при создании keypair: {keypair_error}")
                raise ValueError(f"Не удалось создать keypair из приватного ключа: {keypair_error}")
            
            # Проверка адреса получателя
            try:
                to_pubkey = PublicKey(to_address)
                logger.debug(f"Адрес получателя валиден: {to_pubkey}")
            except Exception as pubkey_error:
                logger.error(f"Ошибка при валидации адреса получателя: {pubkey_error}")
                raise ValueError(f"Неверный адрес получателя: {pubkey_error}")
            
            # Создаем транзакцию
            lamports = int(amount * 1e9)  # Конвертация SOL в lamports
            logger.debug(f"Сумма в ламортах: {lamports}")
            
            transaction = Transaction()
            transaction.add(
                transfer(
                    TransferParams(
                        from_pubkey=from_pubkey,
                        to_pubkey=to_pubkey,
                        lamports=lamports
                    )
                )
            )
            
            # Получаем последний blockhash
            logger.debug("Получаем последний blockhash")
            blockhash_resp = await self.client.get_latest_blockhash()
            recent_blockhash = blockhash_resp.value.blockhash
            # Преобразуем к строке, если это объект
            if hasattr(recent_blockhash, 'to_string'):
                recent_blockhash = recent_blockhash.to_string()
            else:
                recent_blockhash = str(recent_blockhash)
            logger.debug(f"Получен blockhash: {recent_blockhash}")
            transaction.recent_blockhash = recent_blockhash
            
            # Подписываем транзакцию
            logger.debug("Подписываем транзакцию")
            transaction.sign(keypair)
            
            # Проверяем, что транзакция подписана
            if not transaction.signatures or len(transaction.signatures) == 0:
                logger.error("Транзакция не была подписана!")
                raise ValueError("Транзакция не содержит подписей после вызова sign()")
                
            # Логируем информацию о подписи
            logger.debug(f"Транзакция подписана. Сигнатур: {len(transaction.signatures)}")
            
            # Отправляем транзакцию
            logger.debug("Отправляем транзакцию")
            tx_resp = await self.client.send_transaction(transaction, keypair)
            # Обработка ответа в зависимости от типа
            if hasattr(tx_resp, 'value'):
                # solders.rpc.responses.SendTransactionResp
                tx_signature = tx_resp.value
                # Если внутри value есть signature — используем её
                if hasattr(tx_signature, 'signature'):
                    tx_signature = tx_signature.signature
            elif isinstance(tx_resp, dict) and 'result' in tx_resp:
                tx_signature = tx_resp['result']
            else:
                logger.error(f"Ошибка при отправке транзакции: {tx_resp}")
                raise Exception(f"Error sending transaction: {tx_resp}")
            logger.info(f"SOL transfer transaction sent: {tx_signature}")
            return tx_signature
            
        except Exception as e:
            logger.error(f"Error sending SOL: {e}")
            raise
        
    async def send_spl_token(self, from_private_key: str, to_address: str, token_mint: str, amount: float) -> str:
        """
        Отправляет SPL токены (не SOL) с одного адреса на другой.
        
        Args:
            from_private_key: приватный ключ отправителя в base58
            to_address: публичный ключ получателя в base58
            token_mint: адрес токена (mint) в base58
            amount: количество токенов (уже в человеческом формате, например 1.5 USDC)
            
        Returns:
            Подпись транзакции в случае успеха
        """
        try:
            logger.info(f"Beginning SPL token transfer: to_address={to_address}, token_mint={token_mint}, amount={amount}")
            
            # Декодируем приватный ключ и создаём объект keypair
            private_key_bytes = base58.b58decode(from_private_key)
            logger.info(f"Private key decoded successfully, length: {len(private_key_bytes)}")
            
            # Создаем объект keypair из приватного ключа
            keypair = Keypair.from_secret_key(private_key_bytes)
            
            # Создаем PublicKey объекты для адресов
            sender_pubkey = keypair.public_key
            receiver_pubkey = PublicKey(to_address)
            mint_pubkey = PublicKey(token_mint)
            
            logger.info(f"Public keys created: sender={sender_pubkey}, receiver={receiver_pubkey}, mint={mint_pubkey}")
            
            # Получаем информацию о токене (в первую очередь количество десятичных знаков)
            token_supply_response = await self.client.get_token_supply(mint_pubkey)
            logger.info(f"Token supply response type: {type(token_supply_response)}, response: {token_supply_response}")
            
            # Определяем decimals токена из ответа
            token_decimals = None
            if hasattr(token_supply_response, 'value'):
                # Новый формат ответа (объект solders)
                token_decimals = token_supply_response.value.decimals
            elif isinstance(token_supply_response, dict) and 'result' in token_supply_response:
                # Старый формат ответа (словарь)
                token_decimals = token_supply_response['result']['value']['decimals']
            else:
                raise ValueError(f"Unknown response format: {token_supply_response}")
            
            # Конвертируем количество токенов в сырой формат
            token_amount_raw = int(amount * (10 ** token_decimals))
            logger.info(f"Token info: decimals={token_decimals}, raw_amount={token_amount_raw}")
            
            # Импорт необходимых зависимостей
            from spl.token.constants import TOKEN_PROGRAM_ID
            from spl.token.instructions import get_associated_token_address, transfer, create_associated_token_account, TransferParams
            from solana.transaction import Transaction

            # Получаем адреса ассоциированных токен-аккаунтов
            source_token_address = get_associated_token_address(sender_pubkey, mint_pubkey)
            dest_token_address = get_associated_token_address(receiver_pubkey, mint_pubkey)
            
            logger.info(f"Source token address: {source_token_address}, dest token address: {dest_token_address}")
            
            # Проверяем существование адреса получателя
            dest_account_info = await self.client.get_account_info(dest_token_address)
            dest_exists = False
            
            if hasattr(dest_account_info, 'value') and dest_account_info.value is not None:
                dest_exists = True
            elif isinstance(dest_account_info, dict) and dest_account_info.get('result', {}).get('value') is not None:
                dest_exists = True
                
            logger.info(f"Destination account exists: {dest_exists}")
                
            # Создаем транзакцию
            transaction = Transaction()
            
            # Если адрес получателя не существует, создаем его
            if not dest_exists:
                logger.info(f"Creating destination token account for {receiver_pubkey}")
                create_ata_ix = create_associated_token_account(
                    payer=sender_pubkey,
                    owner=receiver_pubkey,
                    mint=mint_pubkey
                )
                transaction.add(create_ata_ix)
                logger.info(f"Added create ATA instruction: {create_ata_ix}")
                
            # Добавляем инструкцию перевода
            transfer_ix = transfer(
                TransferParams(
                    source=source_token_address,
                    dest=dest_token_address,
                    owner=sender_pubkey,
                    amount=token_amount_raw
                )
            )
            transaction.add(transfer_ix)
            logger.info(f"Added transfer instruction: {transfer_ix}")
            
            # Получаем последний blockhash
            recent_blockhash_response = await self.client.get_latest_blockhash()
            recent_blockhash = None
            
            if hasattr(recent_blockhash_response, 'value'):
                recent_blockhash = recent_blockhash_response.value.blockhash
            elif isinstance(recent_blockhash_response, dict) and 'result' in recent_blockhash_response:
                recent_blockhash = recent_blockhash_response['result']['value']['blockhash']
                
            if not recent_blockhash:
                raise Exception(f"Failed to get recent blockhash: {recent_blockhash_response}")
                
            logger.info(f"Got recent blockhash: {recent_blockhash}")
            transaction.recent_blockhash = recent_blockhash
            
            # Подписываем транзакцию
            transaction.sign(keypair)
            logger.info(f"Transaction signed successfully")
            
            # Отправляем транзакцию
            opts = types.TxOpts(skip_preflight=False, skip_confirmation=False)
            tx_response = await self.client.send_transaction(transaction, keypair, opts=opts)
            logger.info(f"Transaction response type: {type(tx_response)}, value: {tx_response}")
            
            # Обрабатываем ответ в разных форматах
            transfer_signature = None
            
            if hasattr(tx_response, 'value'):
                transfer_signature = tx_response.value
                if hasattr(transfer_signature, 'signature'):
                    transfer_signature = transfer_signature.signature
                elif isinstance(transfer_signature, str):
                    # Иногда возвращается просто строка
                    transfer_signature = transfer_signature
            elif isinstance(tx_response, dict) and 'result' in tx_response:
                transfer_signature = tx_response['result']
            elif isinstance(tx_response, str):
                # Иногда API возвращает просто строку с подписью
                transfer_signature = tx_response
                
            if not transfer_signature:
                raise Exception(f"Failed to get transaction signature: {tx_response}")
            
            logger.info(f"SPL token transfer successful: {transfer_signature}")
            return str(transfer_signature)
        
        except Exception as e:
            logger.error(f"Error sending SPL token: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise