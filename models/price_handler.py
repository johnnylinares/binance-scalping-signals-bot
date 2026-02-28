import time
import asyncio
from collections import deque
from binance import BinanceSocketManager
from models.log_handler import log
from models.alert_handler import alert_handler
from models.trade_handler import trade_handler
from config.settings import THRESHOLD, TIME_WINDOW, GROUP_SIZE

# Global price history persistence
global_price_history = {}


async def _handle_websocket_stream(client, streams: list, price_history: dict, group_id: int):
    """Handle websocket stream for a group of currencies."""
    
    await log(f"[Group {group_id}]: Creating websocket for {len(streams)} coins.")
    
    bm = BinanceSocketManager(client)
    ts = bm.futures_multiplex_socket(streams)

    try:
        async with ts as tscm:
            last_cleanup_time = time.time()
            
            while True:
                try:
                    msg = await asyncio.wait_for(tscm.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                # Validate ticker data
                ticker_data = msg.get('data')
                if not isinstance(ticker_data, dict) or ticker_data.get('e') != '24hrTicker':
                    continue
                
                symbol = ticker_data.get('s')
                if symbol not in price_history:
                    continue
                
                try:
                    # Extract price data
                    price = float(ticker_data['c'])
                    volume = float(ticker_data['q'])
                    now = time.time()
                    
                    history = price_history[symbol]
                    history.append((now, price))
                    
                    # Batch cleanup every 60 seconds
                    if now - last_cleanup_time > 60:
                        for hist in price_history.values():
                            while hist and (now - hist[0][0]) > TIME_WINDOW:
                                hist.popleft()
                        last_cleanup_time = now
                    
                    if len(history) < 2:
                        continue

                    old_price = history[0][1]
                    percentage_change = ((price - old_price) / old_price) * 100
                    
                    if abs(percentage_change) >= THRESHOLD:
                        emoji = ("🟢", "📈") if percentage_change > 0 else ("🔴", "📉")
                        
                        try:
                            await log(f"[Group {group_id}] 📊 COIN FOUND: {symbol} ({percentage_change:+.2f}%)")

                            original_msg_id = await alert_handler(
                                symbol, percentage_change, price, emoji, volume
                            )

                            await trade_handler(
                                bm, symbol, percentage_change, price, original_msg_id, volume
                            )

                        except Exception as e:
                            await log(f"[ERROR] Alert/trade failed for {symbol}: {e}")

                        # Reset history to prevent duplicate alerts
                        price_history[symbol] = deque()
                
                except (ValueError, KeyError, TypeError) as e:
                    await log(f"[Group {group_id}]: Data processing error: {e}")
                    continue

    except asyncio.CancelledError:
        await log(f"[Group {group_id}]: Websocket canceled.")
        
    except Exception as e:
        await log(f"[Group {group_id}]: Critical websocket error: {e}")
        
    finally:
        await log(f"[Group {group_id}]: Websocket closed.")


async def price_handler(client, coins, duration_seconds):
    """Main price tracking function."""

    await log("🤖 PRICE TRACKER ACTIVATED")

    global global_price_history
    
    # Remove coins no longer in filtered list
    coins_to_remove = [symbol for symbol in global_price_history.keys() 
                      if symbol not in coins]
    
    for symbol in coins_to_remove:
        del global_price_history[symbol]
        await log(f"[CLEANUP] Removed {symbol} from history")
    
    # Initialize new coins
    for coin in coins:
        if coin not in global_price_history:
            global_price_history[coin] = deque()
    
    price_history = global_price_history
    
    coins_list = list(coins)
    groups = [coins_list[i:i + GROUP_SIZE] for i in range(0, len(coins_list), GROUP_SIZE)]
    
    await log(f"Filtered coins: {len(coins)}. Creating {len(groups)} groups (max {GROUP_SIZE}/group)")
    await log(f"⏰ Cycle duration: {duration_seconds/3600:.1f} hours")
    await log(f"📊 Persistent history: {len(price_history)} coins")

    websocket_tasks = []
    for i, group_coins in enumerate(groups):
        group_id = i + 1
        streams = [f"{coin.lower()}@ticker" for coin in group_coins]
        
        if not streams:
            await log(f"[Group {group_id}] skipped (no coins).")
            continue
        
        task = asyncio.create_task(
            _handle_websocket_stream(client, streams, price_history, group_id)
        )
        websocket_tasks.append(task)

    if not websocket_tasks:
        await log("[WARNING] No tasks created (empty coin list).")
        await asyncio.sleep(duration_seconds)
        return

    try:
        await asyncio.sleep(duration_seconds)
        
    except asyncio.CancelledError:
        await log("[PRICE_HANDLER] Cycle canceled.")
        raise
        
    finally:
        await log("⏰ Cycle completed. Closing websockets...")
        
        for task in websocket_tasks:
            task.cancel()
        
        results = await asyncio.gather(*websocket_tasks, return_exceptions=True)
        
        for i, res in enumerate(results):
            if isinstance(res, Exception) and not isinstance(res, asyncio.CancelledError):
                await log(f"[ERROR] Task {i+1} error: {res}")
                
        await log("✅ All websockets closed.")