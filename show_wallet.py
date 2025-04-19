import base58
from solana.keypair import Keypair
import os

def show_wallet_info(private_key):
    """Показывает информацию о кошельке на основе приватного ключа"""
    try:
        # Пробуем декодировать как base58
        try:
            private_key_bytes = base58.b58decode(private_key)
        except:
            # Если не получилось, пробуем как hex
            private_key_bytes = bytes.fromhex(private_key)
            
        keypair = Keypair.from_secret_key(private_key_bytes)
        public_key = str(keypair.public_key)
        
        print(f"Приватный ключ: {private_key}")
        print(f"Публичный ключ (адрес кошелька): {public_key}")
        
        return True
    except Exception as e:
        print(f"Ошибка при обработке ключа: {e}")
        return False

if __name__ == "__main__":
    print("\n🔍 ПРОВЕРКА WALLET_PRIVATE_KEY ИЗ .ENV")
    print("=" * 50)
    
    # Загружаем ключ из переменной окружения
    env_key = os.getenv("WALLET_PRIVATE_KEY") or "4b9456c0a5d865f962dc97a4a070999bb41357121664104d5fa0343dac2ff424"
    
    print("Проверка ключа из .env файла...")
    if show_wallet_info(env_key):
        print("✅ Ключ успешно проверен")
    else:
        print("❌ Ключ невалидный")
    
    print("\n🔍 ПРОВЕРКА ДРУГОГО КОШЕЛЬКА ИЗ СКРИНШОТА")
    print("=" * 50)
    
    # Эталонный адрес с скриншота
    reference_address = "CSBQ7WT45JS8nrn9nXi2K4FVmpxd2Bq7BDT1x3ECi5p4"
    print(f"Эталонный адрес с скриншота: {reference_address}")
    
    # Проверяем, соответствует ли текущий ключ этому адресу
    if env_key and Keypair.from_secret_key(bytes.fromhex(env_key)).public_key == reference_address:
        print("✅ Текущий ключ соответствует адресу с скриншота")
    else:
        print("❌ Текущий ключ НЕ соответствует адресу с скриншота") 