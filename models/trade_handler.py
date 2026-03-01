import asyncio
import time
import pytz
from datetime import datetime
from models.log_handler import log
from models.alert_handler import tp_sl_alert_handler 
from models.db_handler import insert_trade
from models.operation_handler import OperationHandler
from config.settings import TP_LEVELS, SL_LEVELS, TIME_WINDOW

op_handler = OperationHandler()

# Global trades monitoring pool
active_trades = {}

async def trade_handler(bm, symbol, percentage_change, price, original_message_id, volume):
    """
    Optimized trade handler that shares the main WebSocket connection.
    Uses the existing price stream instead of creating new connections.
    """
    
    # MAIN CONFIG
    entry_price = float(price)
    
    # TIME
    vzla_utc = pytz.timezone('America/Caracas')
    start_time = time.time()
    
    # DIRECTION & LEVELS
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

    # --- INTEGRACIÓN CON OPERATION HANDLER ---
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

    # Add trade to monitoring pool (shared connection)
    trade_id = f"{symbol}_{int(start_time)}"
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
        'sl4_hit': False,
        'active': True,
        'close_price': None,
        'close_time': None,
        'result': 0
    }
    
    await log(f"📊 Added {symbol} {direction} to monitoring pool ({len(active_trades)} active trades)")

async def check_trade_conditions(symbol, current_price):
    """
    Check TP/SL conditions for all active trades of a symbol.
    Called from price_handler when new price data arrives.
    """
    
    current_time = time.time()
    trades_to_remove = []
    
    for trade_id, trade in list(active_trades.items()):
        if not trade['active'] or trade['symbol'] != symbol:
            continue
        
        # Check timeout
        if current_time - trade['start_time'] > TIME_WINDOW:
            await close_trade_timeout(trade_id, current_price)
            trades_to_remove.append(trade_id)
            continue
        
        # Check TP/SL conditions
        if check_tp_sl_hit(trade, current_price):
            trades_to_remove.append(trade_id)
    
    # Remove completed trades
    for trade_id in trades_to_remove:
        await finalize_trade(trade_id)

def check_tp_sl_hit(trade, current_price) -> bool:
    """
    Check if trade hits TP or SL levels.
    Returns True if trade should be closed.
    """
    
    direction = trade['direction']
    tp_prices = trade['tp_prices']
    sl_prices = trade['sl_prices']
    hit_count = trade['hit_count']
    
    if direction == "SHORT":
        # Check SL first (higher prices for short)
        if current_price >= sl_prices[1] and hit_count == 0:
            asyncio.create_task(hit_stop_loss(trade, current_price, sl_prices[1], SL_LEVELS[1]))
            return True
        
        # Check partial SL
        if not trade['sl4_hit'] and hit_count == 0 and current_price >= sl_prices[0]:
            trade['sl4_hit'] = True
        
        # Check TP levels (lower prices for short)
        for i in range(hit_count, len(tp_prices)):
            if current_price <= tp_prices[i]:
                asyncio.create_task(hit_take_profit(trade, current_price, tp_prices[i], TP_LEVELS[i], i))
                trade['hit_count'] = i + 1
                
                if trade['hit_count'] >= len(tp_prices):
                    return True
                break
    
    else:  # LONG
        # Check SL first (lower prices for long)
        if current_price <= sl_prices[1] and hit_count == 0:
            asyncio.create_task(hit_stop_loss(trade, current_price, sl_prices[1], SL_LEVELS[1]))
            return True
        
        # Check partial SL
        if not trade['sl4_hit'] and hit_count == 0 and current_price <= sl_prices[0]:
            trade['sl4_hit'] = True
        
        # Check TP levels (higher prices for long)
        for i in range(hit_count, len(tp_prices)):
            if current_price >= tp_prices[i]:
                asyncio.create_task(hit_take_profit(trade, current_price, tp_prices[i], TP_LEVELS[i], i))
                trade['hit_count'] = i + 1
                
                if trade['hit_count'] >= len(tp_prices):
                    return True
                break
    
    return False

async def hit_take_profit(trade, current_price, tp_price, tp_level, level_index):
    """Handle take profit hit."""
    
    result = tp_level * 100
    await tp_sl_alert_handler(level_index + 1, result, trade['original_message_id'])
    await log(f"🎯 TP Hit: {trade['symbol']} level {level_index + 1} at ${current_price}")

async def hit_stop_loss(trade, current_price, sl_price, sl_level):
    """Handle stop loss hit."""
    
    trade['active'] = False
    trade['close_price'] = sl_price
    trade['close_time'] = datetime.now(pytz.timezone('America/Caracas')).isoformat()
    trade['result'] = -sl_level * 100
    
    result = trade['result']
    await tp_sl_alert_handler(-1, result, trade['original_message_id'])
    await log(f"🛑 SL Hit: {trade['symbol']} at ${current_price}")

async def close_trade_timeout(trade_id, current_price):
    """Close trade due to timeout."""
    
    trade = active_trades[trade_id]
    trade['active'] = False
    trade['close_price'] = current_price
    trade['close_time'] = datetime.now(pytz.timezone('America/Caracas')).isoformat()
    
    # Calculate result based on direction
    side = -1 if trade['direction'] == "SHORT" else 1
    trade['result'] = round(((current_price - trade['entry_price']) / trade['entry_price']) * side * 100, 2)
    
    await tp_sl_alert_handler(0, trade['result'], trade['original_message_id'])
    await log(f"⏰ Trade timeout: {trade['symbol']} at ${current_price}")

async def finalize_trade(trade_id):
    """Finalize trade and save to database."""
    
    trade = active_trades[trade_id]
    
    if trade['close_time'] and trade['close_price']:
        trade_data = {
            "created_at": datetime.fromtimestamp(trade['start_time'], tz=pytz.timezone('America/Caracas')).isoformat(),
            "closed_at": trade['close_time'],
            "symbol": trade['symbol'],
            "direction": trade['direction'],
            "volume": round(trade['volume'], 2),
            "percentage": round(trade['percentage_change'], 2),
            "result": trade['result'],
            "msg_id": trade['original_message_id'],
            "entry_price": trade['entry_price'],
            "close_price": trade['close_price'],
            "sl4_hit": trade['sl4_hit'],
        }
        
        await insert_trade(trade_data)
        await log(f"💾 Trade saved: {trade['symbol']} result: {trade['result']:+.2f}%")
    
    # Remove from active trades
    del active_trades[trade_id]

def get_active_trades_count():
    """Get count of active trades for monitoring."""
    return len(active_trades)