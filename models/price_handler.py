import time
import asyncio
from collections import deque

from binance import BinanceSocketManager
from models.log_handler import log
from models.alert_handler import alert_handler
from models.trade_handler import check_trade_conditions, get_active_trades_count
from config.settings import THRESHOLD, TIME_WINDOW

# Global price history persistence
global_price_history = {}

async def _handle_market_stream(client, price_history: dict):
    """Handle all market mini tickers with single connection using !miniTicker@arr stream."""
    
    await log("🌐 Creating all market mini tickers stream (!miniTicker@arr)")
    
    bm = BinanceSocketManager(client)
    # Usar stream de mini tickers para datos más precisos
    ts = bm.futures_multiplex_socket(['!miniTicker@arr'])  # All market mini tickers

    try:
        await log("🔗 Connecting to Binance all market mini tickers stream...")
        async with ts as tscm:
            await log("✅ Successfully connected to all market mini tickers stream!")
            await log(f"📊 Monitoring {len(price_history)} symbols")
            
            last_cleanup_time = time.time()
            message_count = 0
            alerts_found = 0
            
            while True:
                try:
                    msg = await asyncio.wait_for(tscm.recv(), timeout=1.0)
                    message_count += 1
                    
                    # Log every 500 messages to see activity
                    if message_count % 500 == 0:
                        await log(f"📈 Processed {message_count} messages, found {alerts_found} alerts")
                    
                except asyncio.TimeoutError:
                    continue

                # Validate message structure for !miniTicker@arr
                if not isinstance(msg, dict):
                    continue
                
                # !miniTicker@arr comes as array in 'data' field
                if 'data' not in msg or not isinstance(msg['data'], list):
                    continue
                
                # Process each ticker in the array
                for ticker_data in msg['data']:
                    if not isinstance(ticker_data, dict):
                        continue
                    
                    # Validate mini ticker event
                    if ticker_data.get('e') != '24hrMiniTicker':
                        continue
                    
                    symbol = ticker_data.get('s')
                    if symbol not in price_history:
                        continue
                    
                    try:
                        # Extract price data from mini ticker
                        price_str = ticker_data.get('c')  # Last price
                        volume_str = ticker_data.get('q')  # Volume
                        
                        if price_str is None:
                            if message_count <= 5:  # Debug primeros mensajes
                                await log(f"⚠️ Missing price field for {symbol}: c={price_str}")
                            continue
                        
                        price = float(price_str)
                        volume = float(volume_str) if volume_str else 0.0
                        now = time.time()
                        
                        # Update price history
                        history = price_history[symbol]
                        history.append((now, price))
                        
                        # Check trade conditions for this symbol
                        await check_trade_conditions(symbol, price)
                        
                        # Batch cleanup every 60 segundos
                        if now - last_cleanup_time > 60:
                            await log(f"🧹 Running batch cleanup for {len(price_history)} symbols...")
                            await log(f"📊 Active trades: {get_active_trades_count()}")
                            for hist in price_history.values():
                                while hist and (now - hist[0][0]) > TIME_WINDOW:
                                    hist.popleft()
                            last_cleanup_time = now
                        
                        # Calculate percentage change from our history
                        if len(history) >= 2:
                            old_price = history[0][1]
                            percentage_change = ((price - old_price) / old_price) * 100
                            
                            # Check threshold using our calculation
                            if abs(percentage_change) >= THRESHOLD:
                                alerts_found += 1
                                emoji = ("🟢", "📈") if percentage_change > 0 else ("🔴", "📉")
                                
                                await log(f"📊 COIN FOUND: {symbol} ({percentage_change:+.2f}%)")
                                
                                try:
                                    original_msg_id = await alert_handler(
                                        symbol, percentage_change, price, emoji, volume
                                    )

                                    from models.trade_handler import trade_handler
                                    await trade_handler(
                                        bm, symbol, percentage_change, price, original_msg_id, volume
                                    )

                                except Exception as e:
                                    await log(f"[ERROR] Alert/trade failed for {symbol}: {e}")

                                # Reset history to prevent duplicate alerts
                                price_history[symbol] = deque()
                    
                    except (ValueError, KeyError, TypeError) as e:
                        await log(f"Data processing error for {symbol}: {e}")
                        continue

    except asyncio.CancelledError:
        await log("Market stream canceled.")
        
    except Exception as e:
        await log(f"Critical market stream error: {e}")
        
    finally:
        await log("Market stream closed.")


async def price_handler(client, coins, duration_seconds):
    """
    Main function to manage the websocket tasks using !ticker@arr stream.
    """

    await log("🤖 PRICE TRACKER ACTIVATED")
    await log(f"📊 Monitoring {len(coins)} filtered coins")
    await log(f"⏰ Cycle duration: {duration_seconds/3600:.1f} hours")
    await log(f"🎯 Threshold: {THRESHOLD}%")

    # Use global persistent price history
    global global_price_history
    
    # Update price history with current coins
    current_coins = set(coins)
    existing_coins = set(global_price_history.keys())
    
    # Add new coins to history
    new_coins = current_coins - existing_coins
    for coin in new_coins:
        global_price_history[coin] = deque()
        await log(f"➕ Added new coin to history: {coin}")
    
    # Remove coins no longer in filter
    removed_coins = existing_coins - current_coins
    for coin in removed_coins:
        del global_price_history[coin]
        await log(f"➖ Removed coin from history: {coin}")
    
    await log(f"📈 Price history size: {len(global_price_history)} coins")

    # Create single market stream task
    try:
        await asyncio.wait_for(
            _handle_market_stream(client, global_price_history),
            timeout=duration_seconds + 60
        )
    except asyncio.TimeoutError:
        await log("⏰ Cycle timeout reached. Restarting...")
    except asyncio.CancelledError:
        await log("🔄 Price handler canceled externally.")
        raise
    except Exception as e:
        await log(f"[ERROR] Price handler error: {e}")
        raise
    finally:
        await log("✅ Price handler finished.")