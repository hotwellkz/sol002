from solana.rpc.async_api import AsyncClient
from solana.keypair import Keypair
from solana.publickey import PublicKey
from base58 import b58encode, b58decode
from loguru import logger
from config import SOLANA_RPC_URL, WALLET_PRIVATE_KEY
from typing import Dict, Optional, Tuple
from .firebase_service import FirebaseService
from datetime import datetime
from .utils import encrypt_private_key, decrypt_private_key, get_encryption_cipher
import os

class WalletService:
    def __init__(self):
        # Проверка наличия ENCRYPTION_KEY перед инициализацией
        if not os.getenv("ENCRYPTION_KEY"):
            logger.error("ENCRYPTION_KEY не найден в переменных окружения. Шифрование невозможно.")
            raise ValueError("ENCRYPTION_KEY отсутствует в .env файле. Добавьте ENCRYPTION_KEY для шифрования приватных ключей.")
            
        # Проверка валидности ENCRYPTION_KEY
        try:
            get_encryption_cipher()
            logger.info("Ключ шифрования валиден")
        except Exception as e:
            logger.error(f"Ошибка инициализации шифрования: {e}")
            raise ValueError(f"Ключ шифрования некорректен: {e}")
            
        self.client = AsyncClient(SOLANA_RPC_URL)
        self.firebase = FirebaseService()
        logger.info("Wallet service initialized")
        try:
            if WALLET_PRIVATE_KEY and WALLET_PRIVATE_KEY != 'your_wallet_private_key_here':
                try:
                    # Сначала пробуем расшифровать как hex
                    self.keypair = Keypair.from_secret_key(bytes.fromhex(WALLET_PRIVATE_KEY))
                except ValueError:
                    # Если не получилось, пробуем как base58
                    try:
                        self.keypair = Keypair.from_secret_key(b58decode(WALLET_PRIVATE_KEY))
                    except Exception as e:
                        logger.error(f"Error decoding private key as base58: {e}")
                        raise
            else:
                self.keypair = Keypair()
                logger.warning("No private key provided, using generated keypair")
        except Exception as e:
            logger.error(f"Error initializing wallet: {e}")
            self.keypair = Keypair()
            logger.warning("Using generated keypair due to initialization error")

    async def create_wallet(self, user_id: int) -> Dict:
        """
        Создание нового кошелька Solana для пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            
        Returns:
            Dict: Данные кошелька (public_key, private_key)
        """
        try:
            # Генерация новой пары ключей
            keypair = Keypair()
            public_key = str(keypair.public_key)
            private_key = b58encode(keypair.secret_key).decode('utf-8')
            
            # Шифруем приватный ключ перед сохранением
            encrypted_private_key = encrypt_private_key(private_key)
            logger.debug(f"Приватный ключ зашифрован для пользователя {user_id}")
            
            wallet_data = {
                'public_key': public_key,
                'private_key': encrypted_private_key,  # Сохраняем зашифрованный ключ
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Сохранение в Firebase
            await self.firebase.save_user_wallet(user_id, wallet_data)
            logger.info(f"New wallet created for user {user_id}")
            
            return {
                'public_key': public_key,
                'private_key': private_key
            }
        except Exception as e:
            logger.error(f"Error creating wallet for user {user_id}: {e}")
            raise

    async def get_wallet(self, user_id: int) -> Optional[Dict]:
        """
        Получение данных кошелька пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            
        Returns:
            Optional[Dict]: Данные кошелька или None, если не найдены
        """
        try:
            wallet_data = await self.firebase.get_user_wallet(user_id)
            if wallet_data:
                try:
                    private_key = wallet_data['private_key']
                    logger.debug(f"Got private key for user {user_id}, length: {len(private_key)}")
                    
                    # Проверка, зашифрован ли ключ
                    from .utils import is_encrypted
                    
                    if is_encrypted(private_key):
                        # Расшифровываем приватный ключ
                        decrypted_private_key = decrypt_private_key(private_key)
                        logger.debug(f"Приватный ключ расшифрован для пользователя {user_id}")
                    else:
                        # Ключ не зашифрован, используем как есть
                        logger.warning(f"Key for user {user_id} is not encrypted, using as is")
                        decrypted_private_key = private_key
                        
                        # Шифруем и сохраняем для будущего использования
                        try:
                            encrypted_key = encrypt_private_key(private_key)
                            await self.firebase.save_user_wallet(user_id, {
                                'public_key': wallet_data['public_key'],
                                'private_key': encrypted_key,
                                'updated_at': datetime.utcnow().isoformat()
                            })
                            logger.info(f"Encrypted and saved key for user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to encrypt and save key for user {user_id}: {e}")
                    
                    return {
                        'public_key': wallet_data['public_key'],
                        'private_key': decrypted_private_key
                    }
                except Exception as e:
                    logger.error(f"Ошибка обработки ключа для пользователя {user_id}: {e}")
                    # Если произошла ошибка, пробуем вернуть ключ как есть
                    if len(wallet_data['private_key']) >= 40 and len(wallet_data['private_key']) <= 90:
                        logger.warning(f"Returning raw key for user {user_id} after decryption error")
                        return {
                            'public_key': wallet_data['public_key'],
                            'private_key': wallet_data['private_key']
                        }
                    raise
            return None
        except Exception as e:
            logger.error(f"Error getting wallet for user {user_id}: {e}")
            return None

    async def export_private_key(self, user_id: int) -> Optional[str]:
        """
        Экспорт приватного ключа пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            
        Returns:
            Optional[str]: Приватный ключ или None, если не найден
        """
        try:
            wallet_data = await self.get_wallet(user_id)
            if wallet_data:
                # Сохраняем время экспорта
                await self.firebase.save_export_timestamp(user_id, datetime.utcnow())
                # get_wallet уже возвращает расшифрованный ключ
                return wallet_data['private_key']
            return None
        except Exception as e:
            logger.error(f"Error exporting private key for user {user_id}: {e}")
            return None

    def _create_keypair_from_private_key(self, private_key: str) -> Keypair:
        """
        Создание объекта Keypair из приватного ключа
        
        Args:
            private_key: Приватный ключ в формате base58
            
        Returns:
            Keypair: Объект Keypair Solana
        """
        try:
            secret_key = b58decode(private_key)
            return Keypair.from_secret_key(secret_key)
        except Exception as e:
            logger.error(f"Error creating keypair from private key: {e}")
            raise

    async def get_wallet_info(self):
        """Получение информации о кошельке"""
        try:
            balance = await self.client.get_balance(self.keypair.public_key)
            return {
                'public_key': str(self.keypair.public_key),
                'balance': balance['result']['value'] / 1e9  # Конвертация lamports в SOL
            }
        except Exception as e:
            logger.error(f"Error getting wallet info: {e}")
            raise 