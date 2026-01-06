import os
import ccxt
import time
import threading
from datetime import datetime, timedelta

class OperationHandler:
    def __init__(self):
        """
        Inicializa el gestor de operaciones en modo TESTNET.
        Usa las variables de entorno DEMO_API_KEY y DEMO_API_SECRET.
        """
        self.api_key = os.getenv('DEMO_API_KEY')
        self.api_secret = os.getenv('DEMO_API_SECRET')

        if not self.api_key or not self.api_secret:
            print("⚠️ ADVERTENCIA: No se encontraron DEMO_API_KEY o DEMO_API_SECRET en el entorno.")

        # Conexión a Binance Futures (Testnet)
        self.exchange = ccxt.binanceusdm({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True
            }
        })
        self.exchange.set_sandbox_mode(True) # Activamos modo Testnet
        print("🤖 OperationHandler: Conectado a Binance Futures TESTNET.")

        # Diccionario para rastrear operaciones activas y su tiempo de inicio
        # Key: symbol, Value: { 'entry_time': datetime, 'amount': float }
        self.active_trades = {}
        self.lock = threading.Lock()

        # Iniciar hilo en segundo plano para revisar el tiempo (2 horas)
        self.monitor_thread = threading.Thread(target=self._monitor_timeouts, daemon=True)
        self.monitor_thread.start()

    def process_new_signal(self, signal_data):
        """
        Punto de entrada principal. Evalúa la señal y ejecuta si cumple los requisitos.
        signal_data: {'symbol': str, 'direction': 'SHORT', 'volume': float, 'price': float}
        """
        symbol = signal_data.get('symbol')
        direction = signal_data.get('direction')
        volume = float(signal_data.get('volume', 0))
        price = float(signal_data.get('price', 0))

        # --- FILTROS DE ESTRATEGIA ---
        
        # 1. Solo SHORT
        if direction != 'SHORT':
            # print(f"ignoring {symbol}: Direction is {direction}") # Opcional: reducir ruido
            return

        # 2. Volumen < 100M
        if volume >= 100_000_000:
            print(f"🚫 Ignorado {symbol}: Volumen {volume:,.0f} excesivo (>100M).")
            return

        # Si pasa los filtros, ejecutamos la estrategia
        print(f"⚡ OPORTUNIDAD VÁLIDA: {symbol} | Vol: {volume:,.0f} | Dir: {direction}")
        self._execute_short_strategy(symbol, price)

    def _execute_short_strategy(self, symbol, entry_price_estimate):
        try:
            # Configuración de Capital
            leverage = 10
            margin_usdt = 10.0
            position_size_usdt = margin_usdt * leverage # 100 USDT de posición
            
            # Configuración de Salida
            tp_pct = 0.05
            sl_pct = 0.05

            # 1. Ajustar Apalancamiento
            try:
                self.exchange.set_leverage(leverage, symbol)
            except Exception as e:
                print(f"⚠️ Info Leverage {symbol}: {e}")

            # 2. Calcular cantidad (Amount) precisa
            # Necesitamos el precio actual real para calcular la cantidad exacta de monedas
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            
            amount_raw = position_size_usdt / current_price
            amount = self.exchange.amount_to_precision(symbol, amount_raw)
            
            print(f"🚀 Ejecutanzo SHORT en {symbol}. Margen: ${margin_usdt} (x{leverage})")

            # 3. ENTRADA A MERCADO
            order = self.exchange.create_market_sell_order(symbol, amount)
            real_entry_price = float(order['average']) if order.get('average') else current_price
            print(f"✅ ORDEN EJECUTADA @ {real_entry_price}")

            # 4. CALCULO DE TP Y SL
            # Short: TP es Restar, SL es Sumar
            tp_price = real_entry_price * (1 - tp_pct)
            sl_price = real_entry_price * (1 + sl_pct)

            # Ajustar precisión de precios para Binance
            tp_price = self.exchange.price_to_precision(symbol, tp_price)
            sl_price = self.exchange.price_to_precision(symbol, sl_price)

            # 5. COLOCAR ÓRDENES DE PROTECCIÓN (TP y SL)
            
            # Stop Loss (Market Trigger)
            self.exchange.create_order(symbol, 'STOP_MARKET', 'buy', amount, params={
                'stopPrice': sl_price,
                'reduceOnly': True
            })

            # Take Profit (Limit Order - Para asegurar profit en libro)
            # Nota: Usamos TAKE_PROFIT (trigger) o LIMIT directo. 
            # Para "TP Limit" estricto, usamos TAKE_PROFIT con price y stopPrice iguales o cercanos.
            self.exchange.create_order(symbol, 'TAKE_PROFIT', 'buy', amount, params={
                'stopPrice': tp_price, # Gatillo
                'price': tp_price,     # Precio limite
                'reduceOnly': True
            })

            print(f"🛡️ SL: {sl_price} | 🎯 TP: {tp_price}")

            # 6. REGISTRAR EN MEMORIA (Para el cierre de 2h)
            with self.lock:
                self.active_trades[symbol] = {
                    'entry_time': datetime.now(),
                    'amount': amount
                }

        except Exception as e:
            print(f"❌ ERROR CRÍTICO operando {symbol}: {e}")

    def _monitor_timeouts(self):
        """
        Hilo daemon que revisa cada minuto si alguna operación lleva > 2h abierta.
        """
        print("🕰️ Monitor de tiempo (2h) iniciado...")
        while True:
            try:
                time.sleep(60) # Revisar cada minuto
                now = datetime.now()
                to_remove = []

                with self.lock:
                    # Copiamos items para iterar sin errores
                    for symbol, data in self.active_trades.items():
                        entry_time = data['entry_time']
                        amount = data['amount']
                        
                        # Diferencia de tiempo
                        elapsed = now - entry_time
                        
                        # 2 Horas = 7200 segundos
                        if elapsed.total_seconds() > 7200:
                            print(f"⏰ TIEMPO AGOTADO (2h) para {symbol}. Cerrando a mercado...")
                            self._force_close(symbol, amount)
                            to_remove.append(symbol)
                    
                    # Limpiar lista
                    for symbol in to_remove:
                        del self.active_trades[symbol]

            except Exception as e:
                print(f"⚠️ Error en monitor de tiempo: {e}")

    def _force_close(self, symbol, amount):
        try:
            # 1. Cancelar órdenes abiertas (TP/SL pendientes)
            self.exchange.cancel_all_orders(symbol)
            # 2. Cerrar posición (Market Buy)
            self.exchange.create_market_buy_order(symbol, amount, params={'reduceOnly': True})
            print(f"💀 Operación {symbol} cerrada por tiempo.")
        except Exception as e:
            print(f"❌ Error cerrando {symbol} por tiempo: {e}")