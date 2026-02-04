import os
import json
import hmac
import hashlib
import time
import uuid
import threading
import websocket  # Requiere: pip install websocket-client
from datetime import datetime
from config.settings import DEMO_API_KEY, DEMO_API_SECRET

class OperationHandler:
    def __init__(self):
        """
        Inicializa el gestor de operaciones usando WebSocket directo (Testnet).
        """
        self.api_key = DEMO_API_KEY
        self.secret_key = DEMO_API_SECRET
        self.ws_url = "wss://testnet.binancefuture.com/ws-fapi/v1"

        if not self.api_key or not self.secret_key:
            print("⚠️ ADVERTENCIA: No se encontraron DEMO_API_KEY o DEMO_API_SECRET.")

        # Diccionario para rastrear operaciones activas
        # Key: symbol, Value: { 'entry_time': datetime, 'quantity': float, 'direction': str }
        self.active_trades = {}
        self.lock = threading.Lock()

        # Iniciar monitor de timeouts (2h 10m)
        self.monitor_thread = threading.Thread(target=self._monitor_timeouts, daemon=True)
        self.monitor_thread.start()
        print("🤖 OperationHandler: Iniciado en modo WebSocket (Testnet).")

    def _get_signature(self, params):
        """Genera la firma HMAC SHA256."""
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        return hmac.new(self.secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    def _send_ws_request(self, method, params):
        """
        Abre una conexión efímera para enviar una solicitud y recibir la respuesta.
        Sigue la lógica del test provisto pero síncrono para asegurar orden de ejecución.
        """
        ws = None
        try:
            ws = websocket.create_connection(self.ws_url)
            
            timestamp = int((time.time() * 1000) - 2000)
            
            request_params = {
                "apiKey": self.api_key,
                "timestamp": timestamp,
                **params
            }
            
            request_params["signature"] = self._get_signature(request_params)

            payload = {
                "id": str(uuid.uuid4()),
                "method": method,
                "params": request_params
            }

            ws.send(json.dumps(payload))
            
            response = ws.recv()
            return json.loads(response)

        except Exception as e:
            print(f"❌ Error WS Request: {e}")
            return {"error": str(e)}
        finally:
            if ws:
                ws.close()

    def process_new_signal(self, signal_data):
        """
        Procesa la señal, calcula el tamaño para 100 USDT (10$ x 10x) y ejecuta.
        """
        symbol = signal_data.get('symbol')
        direction = signal_data.get('direction') # 'LONG' o 'SHORT'
        price = float(signal_data.get('price', 0))

        if price == 0:
            return
        position_size_usdt = 100.0
        quantity = position_size_usdt / price
        
        quantity = round(quantity, 3) 
        if quantity == 0:
            quantity = 0.001 # Mínimo de seguridad

        print(f"⚡ PROCESANDO {symbol} ({direction}) | Qty: {quantity} | Precio Ref: {price}")

        side = "BUY" if direction == "LONG" else "SELL"
        
        order_params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity)
        }

        response = self._send_ws_request("order.place", order_params)

        if 'result' in response:
            res = response['result']
            avg_price = float(res.get('avgPrice', price)) # Usar precio real de fill si existe
            print(f"✅ ORDEN EJECUTADA: {symbol} @ {avg_price}")
            
            # Registrar trade
            with self.lock:
                self.active_trades[symbol] = {
                    'entry_time': datetime.now(),
                    'quantity': quantity,
                    'direction': direction,
                    'entry_price': avg_price
                }

            # 3. Colocar TP y SL
            self._place_protection_orders(symbol, direction, quantity, avg_price)
        
        else:
            print(f"❌ Error ejecutando entrada {symbol}: {response}")

    def _place_protection_orders(self, symbol, direction, quantity, entry_price):
        """Coloca TP (10%) y SL (5%)"""
        
        tp_pct = 0.10
        sl_pct = 0.05
        
        tp_price = 0
        sl_price = 0
        close_side = ""

        if direction == "LONG":
            close_side = "SELL"
            tp_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
        else: # SHORT
            close_side = "BUY"
            tp_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)

        # Redondeo de precios (2 decimales por defecto, ajustar según par)
        tp_price = round(tp_price, 2)
        sl_price = round(sl_price, 2)

        print(f"🛡️ Configurando {symbol}: TP {tp_price} | SL {sl_price}")

        # Orden Stop Loss (Market)
        sl_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "stopPrice": str(sl_price),
            "closePosition": "true", # Cierra la posición entera
        }
        self._send_ws_request("order.place", sl_params)

        # Orden Take Profit (Market)
        tp_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": str(tp_price),
            "closePosition": "true",
        }
        self._send_ws_request("order.place", tp_params)

    def _monitor_timeouts(self):
        """
        Revisa cada minuto si una operación lleva abierta más de 2h 10m (7800s).
        """
        while True:
            time.sleep(60)
            now = datetime.now()
            to_remove = []

            with self.lock:
                for symbol, data in self.active_trades.items():
                    elapsed = (now - data['entry_time']).total_seconds()
                    
                    # 2 Horas 10 Minutos = 7800 segundos
                    if elapsed > 7800:
                        print(f"⏰ TIEMPO AGOTADO para {symbol}. Cerrando...")
                        self._close_position(symbol, data)
                        to_remove.append(symbol)
                
                for s in to_remove:
                    del self.active_trades[s]

    def _close_position(self, symbol, data):
        """
        Cierra la posición a mercado y cancela órdenes abiertas.
        """
        # 1. Cancelar todas las órdenes (TP/SL)
        self._send_ws_request("order.cancelAll", {"symbol": symbol})

        # 2. Cerrar posición (Operación contraria)
        side = "SELL" if data['direction'] == "LONG" else "BUY"
        
        close_params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(data['quantity']),
            "reduceOnly": "true"
        }
        
        res = self._send_ws_request("order.place", close_params)
        print(f"💀 Posición cerrada por tiempo: {symbol} | Res: {res.get('result', 'OK')}")