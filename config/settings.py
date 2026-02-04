import os
from dotenv import load_dotenv

load_dotenv()

# BINANCE
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
DEMO_API_KEY = os.getenv("DEMO_API_KEY")
DEMO_API_SECRET = os.getenv("DEMO_API_SECRET")
TESTNET = True

# TELEGRAM
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

# SUPABASE
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# FILTER
MIN_VOLUME = 10 * 1_000_000
MAX_VOLUME = 100 * 1_000_000

# SCAN
THRESHOLD = 20.0
TIME_WINDOW = 7800
GROUP_SIZE = 50

# TRADE
TP_LEVELS = [0.05, 0.10, 0.15, 0.20]
SL_LEVELS = [0.04, 0.05]





