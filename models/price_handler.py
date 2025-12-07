import time
import asyncio
from collections import deque
from binance import BinanceSocketManager
from models.log_handler import log
from models.alert_handler import alert_handler
from models.trade_handler import trade_handler

# MAIN CONFIG

THRESHOLD = 20
TIME_WINDOW = 7800 # 2h10m (s)
GROUP_SIZE = 50

async def alert_worker(bm, symbol, percentage_change, price, emoji, volume, group_id):
    try:
        log_msg = f"[Group {group_id}] 📊 COIN FOUND: {symbol} ({percentage_change:+.2f}%)"
        await log(log_msg)

        original_msg_id = await alert_handler(
            symbol,
            percentage_change,
            price,
            emoji,
            volume
        )

        await trade_handler(
            bm,
            symbol,
            percentage_change,
            price,
            original_msg_id,
            volume
        )

    except Exception as e:
        await log(f"[ERROR] En _process_alert_and_start_trade para {symbol}: {e}")
    

async def _handle_websocket_stream(client, streams: list, price_history: dict, group_id: int):
    """
    An internal function that handles a single multiplexed stream for a group of currencies.
    This task is designed to be started and canceled externally by price_handler.
    """
    
    await log(f"[Group {group_id}]: Creating websocket for {len(streams)} coins.")
    
    bm = BinanceSocketManager(client) # Manager Creation
    ts = bm.futures_multiplex_socket(streams) # Mutiple Socket for Futures

    try:
        async with ts as tscm:
            while True:
                try:
                    msg = await asyncio.wait_for(tscm.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

                if 'data' not in msg or not isinstance(msg['data'], dict):
                    continue
                
                ticker_data = msg['data']
                
                if ticker_data.get('e') != '24hrTicker':
                    continue
                
                symbol = ticker_data.get('s')
                
                if symbol not in price_history:
                    continue
                
                try:
                    price = float(ticker_data['c'])
                    volume = float(ticker_data['q'])
                    now = time.time()
                    
                    history = price_history[symbol]
                    history.append((now, price))
                    
                    while history and (now - history[0][0]) > TIME_WINDOW:
                        history.popleft() 
                    
                    if len(history) < 2:
                        continue

                    old_price = history[0][1]
                    percentage_change = ((price - old_price) / old_price) * 100
                    
                    if abs(percentage_change) >= THRESHOLD:
                        emoji = ("🟢", "📈") if percentage_change > 0 else ("🔴", "📉")
                        
                        asyncio.create_task(alert_worker(bm, symbol, percentage_change, price, emoji, volume, group_id))

                        price_history[symbol] = []
                
                except (ValueError, KeyError, TypeError) as e:
                    asyncio.create_task(log(f"[Group {group_id}]: Error processing data: {e} | Data: {ticker_data}"))
                    continue


    except asyncio.CancelledError:
        await log(f"[Group {group_id}]: Websocket canceled (normal).")
        
    except Exception as e:
        await log(f"[Group {group_id}]: [ERROR] Critic error in websocket: {e}")
        
    finally:
        await log(f"[Group {group_id}]: Websocket closed.")

async def price_handler(client, coins, duration_seconds):
    """
    Main function to manage the websocket tasks.
    """

    await log("🤖 PRICE TRACKER ACTIVATED")

    price_history = {coin: deque() for coin in coins}
    
    coins_list = list(coins)
    groups = [coins_list[i:i + GROUP_SIZE] for i in range(0, len(coins_list), GROUP_SIZE)]
    
    await log(f"Filtered coins: {len(coins)}. Creating {len(groups)} groups (Max {GROUP_SIZE} coins/group)...")
    await log(f"⏰ Cycle duration: {duration_seconds/3600:.1f} hours")

    websocket_tasks = []
    for i, group_coins in enumerate(groups):
        group_id = i + 1
        streams = [f"{coin.lower()}@ticker" for coin in group_coins]
        
        if not streams:
            await log(f"[Group {group_id}] omitted (without coins).")
            continue
        
        task = asyncio.create_task(
            _handle_websocket_stream(client, streams, price_history, group_id)
        )
        websocket_tasks.append(task)

    if not websocket_tasks:
        await log("[WARNING] No websocket tasks were created (empty coin list).")
        await asyncio.sleep(duration_seconds)
        return

    try:
        await asyncio.sleep(duration_seconds)
        
    except asyncio.CancelledError:
        await log("[PRICE_HANDLER] Main cycle canceled externally.")
        raise
        
    finally:
        await log("⏰ Cycle time reached. Closing all websockets...")
        
        for task in websocket_tasks:
            task.cancel()
        
        results = await asyncio.gather(*websocket_tasks, return_exceptions=True)
        
        for i, res in enumerate(results):
            if isinstance(res, Exception) and not isinstance(res, asyncio.CancelledError):
                await log(f"[ERROR] Websocket task {i+1} finished with error: {res}")
                
        await log("✅ All websockets were closed. Price handler finished.")