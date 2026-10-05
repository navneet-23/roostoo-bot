"""Every fixed parameter of the bot in one place.

Nothing here is tuned against live results. The only value selected on data is EMA_N,
chosen in Phase 2 (backtest/RESULTS.md) from the two pre-declared variants.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# --- Universe -------------------------------------------------------------------------------
# The 8 most liquid Roostoo crypto pairs by Binance 30-day USDT quote volume (snapshot taken
# 2026-10-01 from cached Binance Vision 4h klines; see docs/DECISIONS.md). Stablecoins, gold
# tokens and tokenised stocks are excluded. BTC and ETH are included as required.
UNIVERSE = {  # Roostoo pair -> Binance symbol
    "BTC/USD": "BTCUSDT",
    "ETH/USD": "ETHUSDT",
    "ZEC/USD": "ZECUSDT",
    "SOL/USD": "SOLUSDT",
    "XRP/USD": "XRPUSDT",
    "NEAR/USD": "NEARUSDT",
    "BNB/USD": "BNBUSDT",
    "SUI/USD": "SUIUSDT",
}
COINS = list(UNIVERSE)

# --- Bars and clocks -------------------------------------------------------------------------
BAR = "4h"
BAR_MS = 4 * 3600 * 1000
BARS_PER_DAY = 6
BARS_PER_YEAR = 2190
HISTORY_BARS = 400        # bars pulled each cycle; must exceed VOL_LOOKBACK and EMA warm-up
WAKE_DELAY_SEC = 60       # wake this long after each 4h bar close (UTC)
HEARTBEAT_SEC = 15 * 60

# --- Signal ----------------------------------------------------------------------------------
EMA_VARIANTS = (50, 100)  # pre-declared; nothing else is searched
EMA_N = 100               # set from Phase 2 (backtest/RESULTS.md)
RET_LOOKBACK = 14 * BARS_PER_DAY     # 14-day return, in bars
VOL_LOOKBACK = 30 * BARS_PER_DAY     # 30-day realised vol, in bars

# --- Sizing ----------------------------------------------------------------------------------
TARGET_VOL = 0.25         # annualised portfolio target volatility
MAX_WEIGHT = 0.25         # per-coin cap, fraction of equity
MAX_GROSS = 0.95          # longs + short collateral, fraction of equity
NO_TRADE_BAND = 0.03      # skip a trade if |target - current| <= 3% of equity

# --- Drawdown stop ---------------------------------------------------------------------------
DD_STOP = 0.08            # close everything when equity is 8% below its running peak
COOLDOWN_SEC = 24 * 3600  # stay flat this long after a stop
REDUCED_SIZE = 0.5        # size multiplier after the cooldown until a new equity peak

# --- Costs (used by the backtest and for logging) ---------------------------------------------
FEE_TAKER = 0.001
FEE_SHORT = 0.001         # per side
SLIPPAGE = 0.0005         # backtest only

# --- API -------------------------------------------------------------------------------------
ROOSTOO_URL = "https://mock-api.roostoo.com"
BINANCE_URLS = ("https://api.binance.com", "https://data-api.binance.vision")
RATE_LIMIT_CALLS = 20     # Roostoo allows 30/min; keep a margin
RATE_LIMIT_WINDOW_SEC = 60
HTTP_TIMEOUT_SEC = 15
MAX_RETRIES = 3

# --- Runtime ---------------------------------------------------------------------------------
MODE = os.getenv("MODE", "dry_run").strip().lower()
API_KEY = os.getenv("ROOSTOO_API_KEY", "").strip()
SECRET_KEY = os.getenv("ROOSTOO_SECRET_KEY", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_DIR = os.path.join(ROOT, "state")
LOG_DIR = os.path.join(ROOT, "logs")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
PRICE_STORE = os.path.join(STATE_DIR, "roostoo_prices.csv")
