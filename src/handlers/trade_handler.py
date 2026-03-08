import asyncio
import time
import pytz
from datetime import datetime
from handlers.log_handler import log
from handlers.alert_handler import tp_sl_alert_handler 
from handlers.db_handler import insert_trade
from handlers.operation_handler import OperationHandler
from config.settings import TP_LEVELS, SL_LEVELS, TIME_WINDOW

op_handler = OperationHandler()

active_trades = {}

async def trade_handler(bm, symbol, percentage_change, price, original_message_id, volume):
    entry_price = float(price)
    start_time = time.time()
    
    if percentage_change > 0:
        tp_prices = [entry_price * (1 - tp) for tp in TP_LEVELS]
        sl_prices = [entry_price * (1 + sl) for sl in SL_LEVELS]
        direction = "SHORT"
        side = -1
    else:
        tp_prices = [entry_price * (1 + tp) for tp in TP_LEVELS]
        sl_prices = [entry_price * (1 - sl) for sl in SL_LEVELS]
        direction = "LONG"
        side = 1

    try:
        signal_data = {
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "price": entry_price
        }
        asyncio.get_running_loop().run_in_executor(None, op_handler.process_new_signal, signal_data)
        await log(f"📡 Signal sent to OperationHandler: {symbol} {direction}")
    except Exception as e:
        await log(f"❌ Failed to send signal to OperationHandler: {e}")

    trade_id = f"{symbol}_{int(start_time * 1000)}"
    active_trades[trade_id] = {
        'symbol': symbol,
        'direction': direction,
        'entry_price': entry_price,
        'tp_prices': tp_prices,
        'sl_prices': sl_prices,
        'original_message_id': original_message_id,
        'volume': volume,
        'percentage_change': percentage_change,
        'start_time': start_time,
        'hit_count': 0,
        'active': True,
        'close_price': None,
        'close_time': None,
        'result': None,
        'profit': 0.0
    }
    
    await log(f"📊 Added {symbol} {direction} to monitoring pool ({len(active_trades)} active trades)")

async def check_trade_conditions(symbol, current_price):
    current_time = time.time()
    trades_to_remove = []
    
    for trade_id, trade in list(active_trades.items()):
        if trade['symbol'] != symbol:
            continue
        
        if not trade['active']:
            continue
        
        try:
            if current_time - trade['start_time'] > TIME_WINDOW:
                if trade['result'] is None:
                    await close_trade_timeout(trade_id, current_price)
                trades_to_remove.append(trade_id)
                continue
            
            should_close = await check_tp_sl_hit(trade, current_price)
            if should_close:
                trades_to_remove.append(trade_id)
        except Exception as e:
            await log(f"❌ Error checking trade {trade_id}: {e}")
    
    for trade_id in trades_to_remove:
        try:
            await finalize_trade(trade_id)
        except Exception as e:
            await log(f"❌ Error finalizing trade {trade_id}: {e}")

async def check_tp_sl_hit(trade, current_price) -> bool:
    direction = trade['direction']
    tp_prices = trade['tp_prices']
    sl_prices = trade['sl_prices']
    hit_count = trade['hit_count']
    
    if direction == "SHORT":
        if current_price >= sl_prices[1] and hit_count == 0:
            await hit_stop_loss(trade, current_price, sl_prices[1])
            return True
        
        for i in range(hit_count, len(tp_prices)):
            if current_price <= tp_prices[i]:
                await hit_take_profit(trade, current_price, tp_prices[i], i)
                trade['hit_count'] = i + 1
                
                if trade['hit_count'] >= len(tp_prices):
                    return True
                break
    
    else:
        if current_price <= sl_prices[1] and hit_count == 0:
            await hit_stop_loss(trade, current_price, sl_prices[1])
            return True
        
        for i in range(hit_count, len(tp_prices)):
            if current_price >= tp_prices[i]:
                await hit_take_profit(trade, current_price, tp_prices[i], i)
                trade['hit_count'] = i + 1
                
                if trade['hit_count'] >= len(tp_prices):
                    return True
                break
    
    return False

async def hit_take_profit(trade, current_price, tp_price, level_index):
    tp_level = TP_LEVELS[level_index]
    profit_percentage = tp_level * 100
    
    if level_index == 0:
        result = 'TP1'
        profit_value = 5.0
    elif level_index == 1:
        result = 'TP2'
        profit_value = 10.0
    elif level_index == 2:
        result = 'TP3'
        profit_value = 15.0
    else:
        result = 'TP4'
        profit_value = 20.0
    
    trade['profit'] = profit_value
    trade['result'] = result
    
    if level_index == 3:
        trade['active'] = False
        trade['close_price'] = tp_price
        trade['close_time'] = datetime.now(pytz.timezone('America/Caracas')).isoformat()
    
    try:
        await tp_sl_alert_handler(level_index + 1, profit_percentage, trade['original_message_id'])
        await log(f"🎯 {result}: {trade['symbol']} at ${current_price} ({profit_value:+.1f}%)")
    except Exception as e:
        await log(f"❌ Error sending TP alert for {trade['symbol']}: {e}")

async def hit_stop_loss(trade, current_price, sl_price):
    side = -1 if trade['direction'] == "SHORT" else 1
    profit_percentage = round(((sl_price - trade['entry_price']) / trade['entry_price']) * side * 100, 2)
    
    trade['active'] = False
    trade['close_price'] = sl_price
    trade['close_time'] = datetime.now(pytz.timezone('America/Caracas')).isoformat()
    trade['profit'] = -5.0
    trade['result'] = 'SL'
    
    try:
        await tp_sl_alert_handler(-1, profit_percentage, trade['original_message_id'])
        await log(f"🛑 SL: {trade['symbol']} at ${current_price} (profit: -5.0%)")
    except Exception as e:
        await log(f"❌ Error sending SL alert for {trade['symbol']}: {e}")

async def close_trade_timeout(trade_id, current_price):
    trade = active_trades[trade_id]
    
    side = -1 if trade['direction'] == "SHORT" else 1
    profit_percentage = round(((current_price - trade['entry_price']) / trade['entry_price']) * side * 100, 2)
    
    trade['active'] = False
    trade['close_price'] = current_price
    trade['close_time'] = datetime.now(pytz.timezone('America/Caracas')).isoformat()
    trade['profit'] = profit_percentage
    trade['result'] = 'TIME'
    
    try:
        await tp_sl_alert_handler(0, profit_percentage, trade['original_message_id'])
        await log(f"⏰ TIME: {trade['symbol']} at ${current_price} ({profit_percentage:+.1f}%)")
    except Exception as e:
        await log(f"❌ Error sending TIME alert for {trade['symbol']}: {e}")

async def finalize_trade(trade_id):
    if trade_id not in active_trades:
        await log(f"⚠️ Trade {trade_id} already removed")
        return
    
    trade = active_trades[trade_id]
    
    if trade['close_time'] and trade['close_price']:
        trade_data = {
            "created_at": datetime.fromtimestamp(trade['start_time'], tz=pytz.timezone('America/Caracas')).isoformat(),
            "closed_at": trade['close_time'],
            "symbol": trade['symbol'],
            "direction": trade['direction'],
            "volume": round(trade['volume'], 2),
            "percentage": round(trade['percentage_change'], 2),
            "profit": trade['profit'],
            "msg_id": trade['original_message_id'],
            "entry_price": trade['entry_price'],
            "close_price": trade['close_price'],
            "result": trade['result'],
        }
        
        await insert_trade(trade_data)
        await log(f"💾 Trade saved: {trade['symbol']} result: {trade['result']} profit: {trade['profit']:+.2f}%")
    
    del active_trades[trade_id]

def get_active_trades_count():
    return len(active_trades)