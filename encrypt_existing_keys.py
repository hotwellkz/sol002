import asyncio
import os
import sys
from loguru import logger
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Проверяем ключ шифрования
if not os.getenv("ENCRYPTION_KEY"):
    logger.error("ENCRYPTION_KEY не найден в переменных окружения.")
    print("Ошибка: ENCRYPTION_KEY отсутствует в .env файле. Добавьте этот ключ для шифрования.")
    sys.exit(1)

from services.firebase_service import FirebaseService
from services.utils import encrypt_private_key

async def encrypt_user_private_key(user_id: int):
    """
    Шифрует приватный ключ пользователя, если он еще не зашифрован
    
    Args:
        user_id: ID пользователя
    """
    firebase = FirebaseService()
    
    # Получаем данные кошелька
    wallet_data = await firebase.get_user_wallet(user_id)
    
    if not wallet_data:
        logger.error(f"Кошелек пользователя {user_id} не найден")
        print(f"Ошибка: Кошелек пользователя {user_id} не найден в базе данных")
        return False
    
    # Проверяем наличие приватного ключа
    if 'private_key' not in wallet_data:
        logger.error(f"Приватный ключ не найден в данных кошелька пользователя {user_id}")
        print(f"Ошибка: Приватный ключ отсутствует в данных кошелька")
        return False
    
    private_key = wallet_data['private_key']
    
    try:
        # Проверяем, возможно ключ уже зашифрован
        # Зашифрованные ключи обычно начинаются с 'g' для Fernet и имеют определенную длину
        if len(private_key) > 100 and private_key.startswith('g'):
            logger.info(f"Ключ пользователя {user_id} уже зашифрован")
            print(f"Ключ пользователя {user_id} уже зашифрован")
            return True
        
        # Шифруем приватный ключ
        encrypted_key = encrypt_private_key(private_key)
        logger.info(f"Ключ пользователя {user_id} успешно зашифрован")
        
        # Обновляем данные в wallet_data
        wallet_data['private_key'] = encrypted_key
        
        # Сохраняем обновленные данные в Firebase
        success = await firebase.save_user_wallet(user_id, wallet_data)
        
        if success:
            logger.info(f"Зашифрованный ключ пользователя {user_id} успешно сохранен в базе данных")
            print(f"Успех: Ключ пользователя {user_id} зашифрован и сохранен в базе данных")
            return True
        else:
            logger.error(f"Ошибка при сохранении зашифрованного ключа пользователя {user_id}")
            print(f"Ошибка: Не удалось сохранить зашифрованный ключ в базе данных")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при шифровании ключа пользователя {user_id}: {e}")
        print(f"Ошибка: {e}")
        return False

async def encrypt_all_users_keys():
    """
    Шифрует приватные ключи всех пользователей в базе данных
    """
    firebase = FirebaseService()
    
    # Получаем список всех пользователей
    try:
        users = await firebase.get_all_users()
        if not users:
            print("Не найдено пользователей в базе данных")
            return
            
        print(f"Найдено {len(users)} пользователей в базе данных")
        
        success_count = 0
        error_count = 0
        already_encrypted_count = 0
        no_wallet_count = 0
        
        for user_id in users:
            print(f"\nОбработка пользователя {user_id}...")
            
            # Получаем данные кошелька
            wallet_data = await firebase.get_user_wallet(user_id)
            
            if not wallet_data:
                print(f"  Кошелек не найден")
                no_wallet_count += 1
                continue
                
            if 'private_key' not in wallet_data:
                print(f"  Приватный ключ отсутствует в данных кошелька")
                error_count += 1
                continue
                
            private_key = wallet_data['private_key']
            
            # Проверяем, зашифрован ли уже ключ
            if len(private_key) > 100 and private_key.startswith('g'):
                print(f"  Ключ уже зашифрован")
                already_encrypted_count += 1
                continue
                
            try:
                # Шифруем приватный ключ
                encrypted_key = encrypt_private_key(private_key)
                
                # Обновляем данные в wallet_data
                wallet_data['private_key'] = encrypted_key
                
                # Сохраняем обновленные данные в Firebase
                success = await firebase.save_user_wallet(user_id, wallet_data)
                
                if success:
                    print(f"  Ключ успешно зашифрован и сохранен")
                    success_count += 1
                else:
                    print(f"  Ошибка при сохранении зашифрованного ключа")
                    error_count += 1
            except Exception as e:
                print(f"  Ошибка при шифровании: {e}")
                error_count += 1
        
        # Выводим итоговую статистику
        print("\nИтоги обработки:")
        print(f"  Всего пользователей: {len(users)}")
        print(f"  Успешно зашифровано: {success_count}")
        print(f"  Уже были зашифрованы: {already_encrypted_count}")
        print(f"  Без кошелька: {no_wallet_count}")
        print(f"  Ошибки: {error_count}")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке пользователей: {e}")
        print(f"Ошибка при обработке пользователей: {e}")

async def main():
    print("Запуск процесса шифрования ключей всех пользователей...")
    
    # Выберите один из вариантов:
    
    # 1. Шифрование ключа конкретного пользователя
    user_id = 1620950118  # Замените на ID нужного пользователя
    print(f"\nШифрование ключа пользователя {user_id}...")
    result = await encrypt_user_private_key(user_id)
    
    if result:
        print(f"Ключ пользователя {user_id} успешно зашифрован!")
    else:
        print(f"Ошибка при шифровании ключа пользователя {user_id}")
    
    # 2. Шифрование ключей всех пользователей
    # Раскомментируйте следующую строку, чтобы запустить шифрование для всех пользователей
    # await encrypt_all_users_keys()

if __name__ == "__main__":
    asyncio.run(main())
