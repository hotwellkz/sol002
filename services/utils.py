from cryptography.fernet import Fernet
import os
from loguru import logger

def get_encryption_cipher():
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        logger.error("ENCRYPTION_KEY не найден в переменных окружения. Шифрование невозможно.")
        raise ValueError("ENCRYPTION_KEY не найден в переменных окружения")
    logger.debug(f"Using encryption key: {key[:5]}...")
    return Fernet(key)

def encrypt_private_key(private_key: str) -> str:
    """
    Шифрует приватный ключ и возвращает строку для сохранения
    
    Args:
        private_key: Строка приватного ключа в формате base58
        
    Returns:
        str: Зашифрованная строка
    """
    try:
        logger.debug(f"Encrypting private key, length: {len(private_key)}")
        cipher = get_encryption_cipher()
        encrypted = cipher.encrypt(private_key.encode())
        result = encrypted.decode()
        logger.debug(f"Key encrypted successfully, result length: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Error encrypting private key: {e}")
        raise

def decrypt_private_key(encrypted_key: str) -> str:
    """
    Расшифровывает приватный ключ для использования
    
    Args:
        encrypted_key: Зашифрованная строка приватного ключа
        
    Returns:
        str: Расшифрованный приватный ключ
    """
    try:
        logger.debug(f"Decrypting private key, encrypted length: {len(encrypted_key)}")
        # Проверка, зашифрован ли ключ
        if not encrypted_key.startswith('g'):
            logger.warning("The key doesn't appear to be encrypted with Fernet (doesn't start with 'g')")
            
        cipher = get_encryption_cipher()
        decrypted = cipher.decrypt(encrypted_key.encode())
        result = decrypted.decode()
        logger.debug(f"Key decrypted successfully, result length: {len(result)}")
        return result
    except Exception as e:
        logger.error(f"Error decrypting private key: {e}, key length: {len(encrypted_key)}")
        # Проверка, не является ли ключ уже расшифрованным
        if len(encrypted_key) >= 40 and len(encrypted_key) <= 90:
            logger.warning("The key might already be decrypted (looks like a base58 key)")
            return encrypted_key
        raise

def is_encrypted(key: str) -> bool:
    """
    Проверяет, является ли ключ зашифрованным с помощью Fernet
    
    Args:
        key: Ключ для проверки
        
    Returns:
        bool: True если ключ зашифрован, False если нет
    """
    # Fernet-зашифрованные строки обычно начинаются с 'g'
    return key.startswith('g') and len(key) > 100
