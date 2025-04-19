from aiohttp import ClientSession
from loguru import logger

class PriceService:
    def __init__(self):
        self.coingecko_api = "https://api.coingecko.com/api/v3"

    async def get_token_price_usd(self, symbol_or_address: str) -> float:
        """
        Получает цену токена в USD через CoinGecko (по символу или адресу).
        Возвращает 0.0 если не найден.
        """
        try:
            async with ClientSession() as session:
                # Пробуем по символу
                url = f"{self.coingecko_api}/simple/price?ids={symbol_or_address.lower()}&vs_currencies=usd"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if symbol_or_address.lower() in data and 'usd' in data[symbol_or_address.lower()]:
                            return float(data[symbol_or_address.lower()]['usd'])
                # Если не найдено по символу, пробуем по адресу (contract address)
                url = f"{self.coingecko_api}/simple/token_price/solana?contract_addresses={symbol_or_address}&vs_currencies=usd"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if symbol_or_address in data and 'usd' in data[symbol_or_address]:
                            return float(data[symbol_or_address]['usd'])
        except Exception as e:
            logger.error(f"Failed to get price for {symbol_or_address}: {str(e)}")
        return 0.0

    async def get_token_price_jupiter(self, token_mint: str, jupiter_service, sol_price_usd: float) -> float:
        """
        Получает цену токена в $ через Jupiter API (через SOL).
        Возвращает 0.0 если не найдено.
        """
        try:
            # 1 токен в минимальных единицах (например, USDC - 1_000_000)
            decimals = 9  # по умолчанию
            try:
                decimals = await jupiter_service.get_token_decimals(token_mint)
            except Exception:
                pass
            amount = 10 ** decimals
            # inputMint = token_mint, outputMint = SOL
            SOL_MINT = "So11111111111111111111111111111111111111112"
            route = await jupiter_service.get_best_route(token_mint, SOL_MINT, amount)
            if not route or not route.get('outAmount'):
                return 0.0
            out_amount = int(route['outAmount']) / 1e9  # SOL всегда 9 знаков
            usd = out_amount * sol_price_usd
            return usd
        except Exception as e:
            logger.error(f"Failed to get Jupiter price for {token_mint}: {str(e)}")
            return 0.0

    async def get_sol_price(self) -> float:
        """
        Получает текущую цену SOL в USD через CoinGecko API
        
        Returns:
            float: Цена SOL в USD
            
        Raises:
            Exception: Если не удалось получить цену
        """
        try:
            async with ClientSession() as session:
                url = f"{self.coingecko_api}/simple/price?ids=solana&vs_currencies=usd"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data['solana']['usd']
                        logger.info(f"Current SOL price: ${price}")
                        return float(price)
                    else:
                        raise Exception(f"Error getting SOL price: {response.status}")
                        
        except Exception as e:
            logger.error(f"Failed to get SOL price: {str(e)}")
            # Возвращаем примерную цену как запасной вариант
            return 100.0
