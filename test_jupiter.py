import asyncio
import sys
from services.jupiter_service import JupiterService
from loguru import logger

async def test_quote():
    try:
        js = JupiterService()
        # Тестируем получение котировки
        result = await js._get_quote(
            'So11111111111111111111111111111111111111112', 
            '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # Raydium
            '10000000',  # 0.01 SOL
            1.0
        )
        print('Результат запроса quote:', result is not None)
        if result:
            print('Тип результата:', type(result))
            print('Содержимое:', result)
        return result
    except Exception as e:
        logger.error(f"Ошибка при тестировании: {str(e)}")
        return None

if __name__ == "__main__":
    logger.info("Запуск теста Jupiter API")
    result = asyncio.run(test_quote())
    logger.info(f"Тест завершен, результат: {result is not None}")
