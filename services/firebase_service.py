import firebase_admin
from firebase_admin import credentials, firestore
from loguru import logger
from config import FIREBASE_CREDENTIALS_PATH, FIREBASE_CONFIG
from datetime import datetime
from typing import Dict, Optional

class FirebaseService:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            try:
                cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': FIREBASE_CONFIG['databaseURL']
                })
                self.db = firestore.client()
                self.users_collection = self.db.collection('users')
                logger.info("Firebase initialized successfully")
                self.__class__._initialized = True
            except Exception as e:
                logger.error(f"Error initializing Firebase: {e}")
                raise

    async def save_transaction(self, user_id: int, transaction_data: dict):
        """Сохранение информации о транзакции"""
        try:
            self.db.collection('transactions').add({
                'user_id': user_id,
                'timestamp': transaction_data['timestamp'],
                'type': transaction_data['type'],
                'amount': transaction_data['amount'],
                'status': transaction_data['status']
            })
        except Exception as e:
            logger.error(f"Error saving transaction: {e}")
            raise

    async def get_user_transactions(self, user_id: int):
        """Получение истории транзакций пользователя"""
        try:
            transactions = self.db.collection('transactions').where('user_id', '==', user_id).get()
            return [transaction.to_dict() for transaction in transactions]
        except Exception as e:
            logger.error(f"Error getting user transactions: {e}")
            raise

    async def save_user_wallet(self, user_id: int, wallet_data: Dict) -> bool:
        """
        Сохранение данных кошелька пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            wallet_data: Данные кошелька (public_key, private_key, etc.)
            
        Returns:
            bool: True если сохранение успешно, False в случае ошибки
        """
        try:
            user_doc = self.users_collection.document(str(user_id))
            user_doc.set({
                'wallet': wallet_data,
                'updated_at': datetime.utcnow()
            }, merge=True)
            logger.info(f"Wallet data saved for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving wallet data for user {user_id}: {e}")
            return False

    async def get_user_wallet(self, user_id: int) -> Optional[Dict]:
        """
        Получение данных кошелька пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            
        Returns:
            Optional[Dict]: Данные кошелька или None, если не найдены
        """
        try:
            user_doc = self.users_collection.document(str(user_id)).get()
            if user_doc.exists:
                data = user_doc.to_dict()
                return data.get('wallet')
            return None
        except Exception as e:
            logger.error(f"Error getting wallet data for user {user_id}: {e}")
            return None

    async def save_export_timestamp(self, user_id: int, timestamp: datetime) -> bool:
        """
        Сохранение времени последнего экспорта ключей
        
        Args:
            user_id: ID пользователя в Telegram
            timestamp: Время экспорта
            
        Returns:
            bool: True если сохранение успешно, False в случае ошибки
        """
        try:
            user_doc = self.users_collection.document(str(user_id))
            user_doc.set({
                'last_export': timestamp,
                'updated_at': datetime.utcnow()
            }, merge=True)
            logger.info(f"Export timestamp saved for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving export timestamp for user {user_id}: {e}")
            return False

    async def get_user_data(self, user_id: int) -> Optional[Dict]:
        """
        Получение всех данных пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            
        Returns:
            Optional[Dict]: Все данные пользователя или None, если не найдены
        """
        try:
            user_doc = self.users_collection.document(str(user_id)).get()
            if user_doc.exists:
                return user_doc.to_dict()
            return None
        except Exception as e:
            logger.error(f"Error getting user data for user {user_id}: {e}")
            return None 
            
    async def get_all_users(self) -> list:
        """
        Получение списка ID всех пользователей в базе данных
        
        Returns:
            list: Список ID пользователей
        """
        try:
            users = self.users_collection.stream()
            user_ids = []
            
            for user in users:
                try:
                    # Преобразуем ID документа (строку) в число
                    user_id = int(user.id)
                    user_ids.append(user_id)
                except ValueError:
                    logger.warning(f"Неверный формат ID пользователя: {user.id}")
                    continue
            
            logger.info(f"Найдено {len(user_ids)} пользователей в базе данных")
            return user_ids
        except Exception as e:
            logger.error(f"Ошибка при получении списка пользователей: {e}")
            return []