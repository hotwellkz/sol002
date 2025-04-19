from dotenv import load_dotenv
import os

load_dotenv()

# Bot settings
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]

# Solana settings
SOLANA_RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
SOLANA_WS_URL = os.getenv('SOLANA_WS_URL', 'wss://api.mainnet-beta.solana.com')
WALLET_PRIVATE_KEY = os.getenv('WALLET_PRIVATE_KEY')

# Solana token addresses
from solana_token_addresses import SOLANA_TOKEN_ADDRESSES

# Firebase settings
FIREBASE_CREDENTIALS_PATH = os.getenv('FIREBASE_CREDENTIALS_PATH')
FIREBASE_CONFIG = {
    'apiKey': os.getenv('FIREBASE_API_KEY'),
    'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN'),
    'projectId': os.getenv('FIREBASE_PROJECT_ID'),
    'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET'),
    'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID'),
    'appId': os.getenv('FIREBASE_APP_ID'),
    'databaseURL': os.getenv('FIREBASE_DATABASE_URL')
}

# Jupiter API settings
JUPITER_API_URL = os.getenv('JUPITER_API_URL', 'https://jupiter-swap-api.quiknode.pro/6CA0F7417A18/')
JUPITER_API_KEY = os.getenv('JUPITER_API_KEY', 'QN_e7a3914f4cb94a8bb5cbf7ca29314a3c')
JUPITER_PLATFORM_FEE_BPS = 90  # 0.9%
JUPITER_PLATFORM_FEE_ACCOUNT = 'CSBQ7WT45JS8nrn9nXi2K4FVmpxd2Bq7BDT1x3ECi5p4'

# Helius API settings
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '38cd5b26-9e90-4be9-bde3-a0139463ec0c')

# Logging settings
LOG_FILE = 'logs/transactions.log' 