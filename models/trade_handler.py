import asyncio
import time
import pytz
from datetime import datetime
from models.log_handler import log
from models.alert_handler import tp_sl_alert_handler 
from models.db_handler import insert_trade
from models.operation_handler import OperationHandler

TP_LEVELS = [0.05, 0.10, 0.15, 0.20]
SL_LEVELS = [0.04, 0.05]

# Inicializamos el gestor de operaciones (se conecta a Binance Testnet al iniciar)
op_handler = OperationHandler()

async def trade_handler(bm, symbol, percentage_change, price, original_message_id, volume):

    # MAIN CONFIG
    entry_price = float(price)
    current_price = None
    close_price = None

    # TIME
    vzla_utc = pytz.timezone('America/Caracas')
    start_time = time.time()
    close_time = None

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
        # Ejecutamos en un hilo separado (executor) para no bloquear el loop asíncrono del bot
        asyncio.get_running_loop().run_in_executor(None, op_handler.process_new_signal, signal_data)
        await log(f"TRADE HANDLER: Señal enviada a OperationHandler para {symbol}")
    except Exception as e:
        await log(f"TRADE HANDLER: [ERROR] Fallo al enviar señal a OperationHandler: {e}")

    await log(f"TRADE HANDLER: Monitoreando {symbol} ({percentage_change:+.2f}%)")

    stream = [f"{symbol.lower()}@ticker"]
    ts = bm.futures_multiplex_socket(stream)
    
    hit = 0  # Information TP/SL
    result = 0  # Inicializar result
    sl4_hit = False # Inicializar sl4_hit
    active_trade = True

    try:
        async with ts as tscm:
            while active_trade and time.time() - start_time <= 7800:
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
                
                if direction == "SHORT":
                    if current_price >= sl_prices[1]:
                        if hit == 0:
                            close_price = sl_prices[1]
                            close_time = datetime.now(vzla_utc).isoformat()
                            result = -1 * SL_LEVELS[1] * 100
                            hit = -1
                            await tp_sl_alert_handler(hit, result, original_message_id)
                        active_trade = False
                        break
                    
                    elif not sl4_hit and hit == 0 and current_price >= sl_prices[0]:
                        sl4_hit = True

                    for i in range(hit, len(tp_prices)):
                        if hit == i and current_price <= tp_prices[i]:
                            close_price = tp_prices[i]
                            close_time = datetime.now(vzla_utc).isoformat()
                            result = TP_LEVELS[i] * 100
                            hit = i + 1
                            await tp_sl_alert_handler(hit, result, original_message_id)

                            if hit == len(tp_prices):
                                active_trade = False
                            break
                        else:
                            break
                        
                else:
                    if current_price <= sl_prices[1]:
                        if hit == 0:
                            close_price = sl_prices[1]
                            close_time = datetime.now(vzla_utc).isoformat()
                            result = -1 * SL_LEVELS[1] * 100
                            hit = -1
                            await tp_sl_alert_handler(hit, result, original_message_id)
                        active_trade = False
                        break
                    
                    elif not sl4_hit and hit == 0 and current_price <= sl_prices[0]:
                        sl4_hit = True

                    for i in range(hit, len(tp_prices)):
                        if hit == i and current_price >= tp_prices[i]:
                            close_price = tp_prices[i]
                            close_time = datetime.now(vzla_utc).isoformat()
                            result = TP_LEVELS[i] * 100
                            hit = i + 1
                            await tp_sl_alert_handler(hit, result, original_message_id)

                            if hit == len(tp_prices):
                                active_trade = False
                            break
                        else:
                            break
            if hit == 0 and time.time() - start_time > 7800:
                close_price = current_price
                close_time = datetime.now(vzla_utc).isoformat()
                result = round(((close_price - entry_price) / entry_price) * side * 100, 2)
                await tp_sl_alert_handler(hit, result, original_message_id)
                
                    
    except asyncio.CancelledError:
        await log(f"TRADE HANDLER: Monitoreo de {symbol} cancelado.")
        if close_time is None:
            close_time = datetime.now(vzla_utc).isoformat()
        if close_price is None:
            close_price = current_price
        return
    except Exception as e:
        await log(f"TRADE HANDLER: [ERROR] en socket de {symbol}: {e}")
        if close_time is None:
            close_time = datetime.now(vzla_utc).isoformat()
        if close_price is None:
            close_price = current_price
        return

    finally:
        if close_time is None:
            await log(f"TRADE HANDLER: Monitoreo de {symbol} finalizado sin cierre. No se insertará en DB.")
            return
        
        trade_data = {
            "created_at": datetime.fromtimestamp(start_time, tz=vzla_utc).isoformat(),
            "closed_at": close_time,
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