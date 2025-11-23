import asyncio
import time
from datetime import datetime
from models.log_handler import log
from models.alert_handler import tp_sl_alert_handler 
from models.db_handler import insert_trade

TP_LEVELS = [0.05, 0.10, 0.15, 0.20]
SL_LEVELS = [0.04, 0.05]

async def trade_handler(bm, symbol, percentage_change, price, original_message_id, volume):

    # PRICE
    entry_price = price
    current_price = None
    close_price = None

    # TIME
    start_time = datetime.now('America/Caracas').isoformat()
    close_time = None

    # DIRECTION & LEVELS
    if percentage_change > 0:
        tp_prices = [entry_price * (1 - tp) for tp in TP_LEVELS]
        sl_prices = [entry_price * (1 + sl) for sl in SL_LEVELS]
        direction = "SHORT"
    else:
        tp_prices = [entry_price * (1 + tp) for tp in TP_LEVELS]
        sl_prices = [entry_price * (1 - sl) for sl in SL_LEVELS]
        direction = "LONG"

    await log(f"TRADE HANDLER: Monitoreando {symbol} ({percentage_change:+.2f}%)")

    stream = [f"{symbol.lower()}@ticker"]
    ts = bm.futures_multiplex_socket(stream)
    
    hit = 0  # Information TP/SL
    result = 0.0  # Inicializar result

    async def hited(hit_type, entry_price, close_price, percentage_change):
        """Calcula el resultado del trade y envía alerta"""
        if percentage_change > 0:
            calc_result = round(((entry_price / close_price) - 1) * 100, 2)
        else:
            calc_result = round(((close_price / entry_price) - 1) * 100, 2)
        
        await tp_sl_alert_handler(hit_type, calc_result, close_price, original_message_id)
        return calc_result

    try:
        async with ts as tscm:
            while hit != 4 and hit != -1 and time.time() - start_time < 7800:
                try:
                    msg = await asyncio.wait_for(tscm.recv(), timeout=60.0)
                except asyncio.TimeoutError:
                    continue

                if 'data' not in msg or not isinstance(msg['data'], dict):
                    continue
                
                ticker_data = msg['data']
                
                if ticker_data.get('s') != symbol:
                    continue
                
                try:
                    current_price = float(ticker_data['c'])
                except (ValueError, KeyError, TypeError):
                    continue
                
                # SHORT (percentage_change > 0)
                if percentage_change > 0:
                    if hit == 0 and current_price >= sl_prices[0]:
                        sl4_hit = True

                    elif hit == 0 and current_price >= sl_prices[1]:
                        close_price = sl_prices[1]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(-1, entry_price, close_price, percentage_change)
                        hit = -1

                    elif hit == 0 and current_price <= tp_prices[0]:
                        close_price = tp_prices[0]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(1, entry_price, close_price, percentage_change)
                        hit = 1

                    elif hit == 1 and current_price <= tp_prices[1]:
                        close_price = tp_prices[1]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(2, entry_price, close_price, percentage_change)
                        hit = 2

                    elif hit == 2 and current_price <= tp_prices[2]:
                        close_price = tp_prices[2]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(3, entry_price, close_price, percentage_change)
                        hit = 3

                    elif hit == 3 and current_price <= tp_prices[3]:
                        close_price = tp_prices[4]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(4, entry_price, close_price, percentage_change)
                        hit = 4
                        
                # LONG (percentage_change < 0)
                else:
                    if hit == 0 and current_price <= sl_prices[0]:
                        sl4_hit = True

                    elif hit == 0 and current_price <= sl_prices[1]:
                        close_price = sl_prices[1]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(-1, entry_price, close_price, percentage_change)
                        hit = -1

                    elif hit == 0 and current_price >= tp_prices[0]:
                        close_price = tp_prices[0]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(1, entry_price, close_price, percentage_change)
                        hit = 1
                        
                        
                    elif hit == 1 and current_price >= tp_prices[1]:
                        close_price = tp_prices[1]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(2, entry_price, close_price, percentage_change)
                        hit = 2

                    elif hit == 2 and current_price >= tp_prices[2]:
                        close_price = tp_prices[2]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(3, entry_price, close_price, percentage_change)
                        hit = 3

                    elif hit == 3 and current_price >= tp_prices[3]:
                        close_price = tp_prices[3]
                        closed_at = datetime.now('America/Caracas').isoformat()
                        result = await hited(4, entry_price, close_price, percentage_change)
                        hit = 4

            # Manejar timeout - cerrar trade si no llegó a ningún TP/SL
            if time.time() - start_time >= 7800 and hit == 0:
                close_price = current_price
                closed_at = datetime.now('America/Caracas').isoformat()
                result = await hited(0, entry_price, close_price, percentage_change)
                    
    except asyncio.CancelledError:
        await log(f"TRADE HANDLER: Monitoreo de {symbol} cancelado.")
        if closed_at is None:
            closed_at = datetime.now('America/Caracas').isoformat()
        if close_price is None:
            close_price = current_price
        return
    except Exception as e:
        await log(f"TRADE HANDLER: [ERROR] en socket de {symbol}: {e}")
        if closed_at is None:
            closed_at = datetime.now('America/Caracas').isoformat()
        if close_price is None:
            close_price = current_price
        return

    finally:
        if closed_at is None:
            await log(f"TRADE HANDLER: Monitoreo de {symbol} finalizado sin cierre. No se insertará en DB.")
            return
        
        trade_data = {
            "created_at": start_time,
            "closed_at": closed_at,
            "symbol": symbol,
            "direction": direction,
            "volume": round(volume, 2),
            "percentage": round(percentage_change, 2),
            "result": result,
            "msg_id": original_message_id,
            "entry_price": entry_price,
            "close_price": close_price,
            "sl4_hit": sl4_hit,
        }
        
        await insert_trade(trade_data)
        await log(f"TRADE HANDLER: Finalizado monitoreo de {symbol}.")