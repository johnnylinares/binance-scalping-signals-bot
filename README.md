# Binance Scalping Signals Bot

#### Video Demo: https://youtu.be/-E8tzhUWzwg

#### Description:

The **Binance Scalping Signals Bot** is an automated trading tool designed to monitor the cryptocurrency futures market in real-time. As a cryptocurrency trader with two years of experience, I noticed that manually tracking hundreds of assets for sudden volatility is impossible for a human. I often saw similar bots in paid Telegram channels and decided to challenge myself to build my own version, tailored to my specific "contrarian" scalping strategy, while deepening my understanding of Python, asynchronous programming, and API integration.

This project solves a specific problem: **detecting significant price anomalies (volatility spikes) and managing the subsequent trade simulation automatically.**

### How it Works

The bot connects to the Binance Futures API to retrieve market data. It does not monitor every single coin blindly; instead, it applies a smart filter based on 24-hour trading volume to ensure liquidity and avoid "pump and dump" schemes on low-cap coins. Once the coins are selected, the bot opens multiple WebSocket connections to track their prices in real-time.

The core logic revolves around a "Time Bucket" system. The bot records price snapshots and calculates the percentage change over a sliding window (configurable, default is 2 hours and 10 minutes). If a coin moves more than **20%** (up or down) within this window, the bot considers it a "signal." It immediately sends an alert to a Telegram channel and, crucial to this project, initiates a **Trade Handler**. This handler continues to track the coin to simulate a trade (Long or Short) against the trend, checking for Take Profit (TP) or Stop Loss (SL) levels, and finally logging the result to a Supabase database.

### File Structure and Functionality

The project is structured into modular components to separate concerns (connection, logic, alerting, and data persistence). Here is a detailed breakdown of the files I created:

- **`main.py`**:
    This is the entry point of the application. It initializes the `Binance AsyncClient` and starts the main infinite loop. Inside this loop, it calls the `coin_handler` to refresh the list of monitored coins every 6 hours (to account for new listings or volume changes). It also runs a lightweight **Flask** web server in a separate thread. This design choice was made to satisfy health checks on cloud hosting platforms (like Render or Heroku) which require a web service to keep the bot running 24/7.

- **`models/coin_handler.py`**:
    This module is responsible for the initial filtering. It fetches all available tickers from Binance Futures. I implemented a logic filter here: it only selects pairs ending in `USDT` with a 24-hour quote volume between **$10M and $1B**. This effectively filters out "dead" coins and overly stable coins, leaving only the ones with the right volatility for scalping.

- **`models/price_handler.py`**:
    This is the heart of the detection logic. It receives the filtered list of coins and manages the WebSocket connections. Instead of opening one socket per coin (which would hit API limits), I used `BinanceSocketManager` to multiplex streams in batches (groups of 50). It maintains a `deque` (double-ended queue) for each coin to store price history efficiently. When the threshold (20%) is breached, it triggers the `alert_worker`.

- **`models/alert_handler.py`**:
    This module handles the communication with the user. It uses the `python-telegram-bot` library to send formatted messages with emojis (🟢/🔴) indicating the direction of the signal. It also contains logic to update the user on the trade status (e.g., replying to the original message when a TP or SL is hit).

- **`models/trade_handler.py`**:
    Perhaps the most complex logic resides here. Once a signal is found, this handler "watches" that specific coin intensely for a set period (e.g., 2 hours). It calculates entry price, target prices (TP 1-4), and stop-loss levels based on predefined percentages. It uses a dedicated WebSocket stream for this specific coin to ensure zero latency in tracking the outcome. Once the trade concludes (win, loss, or timeout), it calls the database handler.

- **`models/db_handler.py`**:
    This file manages the connection to **Supabase** (PostgreSQL). It contains the `insert_trade` function, which saves the full metadata of the signal (symbol, entry price, result percentage, duration) for future statistical analysis.

- **`config/settings.py`**:
    A centralized place to load environment variables (API keys, secrets, bot tokens) using `python-dotenv`, ensuring sensitive data is not hardcoded.

### Design Choices

**1. Asynchronous Programming (`asyncio`)**
One of the biggest design decisions was to build the entire bot using `asyncio` instead of threading or synchronous code. Tracking hundreds of WebSocket streams and processing messages in real-time requires high concurrency. A synchronous approach would have introduced lag, potentially causing the bot to miss the exact second a price spike occurred. `asyncio` allows the bot to handle thousands of I/O operations per second with minimal resource overhead.

**2. The Volume Filter**
I debated whether to monitor *all* coins or filter them. I chose to filter by volume (10M - 1B) because, in my trading experience, coins with very low volume are susceptible to market manipulation, while coins with massive volume (like Bitcoin or Ethereum) rarely move 20% in a short time. This design choice optimizes the bot's resources to focus only on "viable" scalping targets.

**3. Separation of Alerting and Tracking**
Initially, I considered just sending the alert and forgetting about it. However, I decided to implement the `trade_handler` to make the project "stateful." The bot doesn't just notify; it *follows through*. This required passing the Telegram `message_id` between functions so the bot could reply to its own specific alert with the result (Win/Loss), creating a clean and organized user experience in the Telegram channel.

---

## 🛠️ Installation & Usage

### 1. Clone the repository

```bash
git clone [https://github.com/johnnylinares/binance-scalping-signals-bot.git](https://github.com/johnnylinares/binance-scalping-signals-bot.git)
cd binance-scalping-signals-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
Create a .env file in the project's root:

Fragmento de código

#### Binance API
```bash
API_KEY="your_binance_api_key"
API_SECRET="your_binance_api_secret"
```

#### Main Telegram Bot

```bash
BOT_TOKEN="your_bot_token"
CHANNEL_ID="your_channel_id"
```

#### Database

```bash
SUPABASE_URL="your_supabase_url"
SUPABASE_SERVICE_KEY="your_supabase_key"
```

### 4. Run the bot

```bash
python main.py
```

⚠️ Disclaimer
This bot is for educational and informational purposes only. It does not constitute financial advice. Always do your own research before making investment decisions.
