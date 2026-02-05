from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from config.settings import DEMO_API_KEY, DEMO_API_SECRET

class OperationHandler:
    def __init__(self):
        """
        Inicializa el gestor de operaciones usando Client Síncrono para Testnet.
        """
        self.api_key = DEMO_API_KEY
        self.secret_key = DEMO_API_SECRET
        self.hedge_mode = False # Por defecto asumimos One-way
        
        # Inicializar cliente en modo Testnet
        try:
            self.client = Client(self.api_key, self.secret_key, testnet=True)
            print("🤖 OperationHandler: Conectado a Binance Futures TESTNET.")
            
            # Detectar modo de posición (Hedge vs One-Way) para evitar errores de cierre
            self._check_position_mode()
            
        except Exception as e:
            print(f"⚠️ OperationHandler: Error conectando a Binance: {e}")

    def _check_position_mode(self):
        """Revisa si la cuenta está en Hedge Mode o One-Way Mode"""
        try:
            info = self.client.futures_get_position_mode()
            # {'dualSidePosition': True} -> Hedge Mode
            # {'dualSidePosition': False} -> One-Way Mode
            if info['dualSidePosition']:
                self.hedge_mode = True
                print("ℹ️ Modo detectado: HEDGE MODE (Se usará positionSide)")
            else:
                self.hedge_mode = False
                print("ℹ️ Modo detectado: ONE-WAY MODE")
        except Exception as e:
            print(f"⚠️ No se pudo obtener modo de posición: {e}. Asumiendo One-Way.")

    def _get_symbol_info(self, symbol):
        """
        Obtiene precisiones y tick_size exacto del par.
        """
        try:
            info = self.client.futures_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    qty_precision = int(s['quantityPrecision'])
                    price_precision = int(s['pricePrecision'])
                    tick_size = 0.01 # Fallback
                    
                    # Buscar filtro PRICE_FILTER para tickSize exacto
                    for f in s['filters']:
                        if f['filterType'] == 'PRICE_FILTER':
                            tick_size = float(f['tickSize'])
                            break
                            
                    return qty_precision, price_precision, tick_size
        except:
            pass
        return 3, 2, 0.01

    def _round_step(self, value, step):
        """
        Redondea el valor al escalón (tick_size) más cercano.
        Ej: value=100.051, step=0.01 -> 100.05
        """
        return round(value / step) * step

    def process_new_signal(self, signal_data):
        """
        1. Recibe señal.
        2. Entra en CONTRA de la tendencia.
        3. Coloca TP y SL duros usando reglas de precisión estrictas y modo de posición.
        """
        symbol = signal_data.get('symbol')
        signal_direction = signal_data.get('direction') 
        ref_price = float(signal_data.get('price', 0))

        if not symbol or ref_price == 0:
            return

        # ---------------------------------------------------------
        # 1. LÓGICA DE DIRECCIÓN Y MODE
        # ---------------------------------------------------------
        # Estrategia Contrarian:
        # Señal LONG -> Entramos SHORT
        # Señal SHORT -> Entramos LONG
        
        if signal_direction == "SHORT":
            # Vamos a abrir SHORT
            side_entry = SIDE_SELL
            side_exit = SIDE_BUY
            # Si es Hedge Mode, debemos especificar que operamos el lado 'SHORT'
            position_side = 'SHORT' if self.hedge_mode else 'BOTH'
            user_msg = "SHORT"
        else:
            # Vamos a abrir LONG
            side_entry = SIDE_BUY
            side_exit = SIDE_SELL
            # Si es Hedge Mode, debemos especificar que operamos el lado 'LONG'
            position_side = 'LONG' if self.hedge_mode else 'BOTH'
            user_msg = "LONG"

        print(f"⚡ PROCESANDO {symbol} | Señal: {signal_direction} -> Operando: {user_msg}")

        try:
            # ---------------------------------------------------------
            # 2. OBTENER INFORMACIÓN DE MERCADO
            # ---------------------------------------------------------
            qty_precision, price_precision, tick_size = self._get_symbol_info(symbol)
            
            # Cambiar apalancamiento
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=10)
            except:
                pass 

            # ---------------------------------------------------------
            # 3. CÁLCULOS
            # ---------------------------------------------------------
            # A) Cantidad
            position_size_usdt = 100.0
            raw_quantity = position_size_usdt / ref_price
            quantity = round(raw_quantity, qty_precision)
            
            # B) Precios TP (10%) y SL (5%)
            tp_pct = 0.10
            sl_pct = 0.05
            
            if user_msg == "LONG":
                raw_tp = ref_price * (1 + tp_pct)
                raw_sl = ref_price * (1 - sl_pct)
            else: # SHORT
                raw_tp = ref_price * (1 - tp_pct)
                raw_sl = ref_price * (1 + sl_pct)

            # C) Redondeo estricto por tick_size (Evita errores de filtro)
            tp_price = self._round_step(raw_tp, tick_size)
            sl_price = self._round_step(raw_sl, tick_size)

            # D) Formateo string para la API
            tp_str = "{:.{}f}".format(tp_price, price_precision)
            sl_str = "{:.{}f}".format(sl_price, price_precision)

            print(f"📝 PLAN: Qty:{quantity} | Ref:{ref_price} | TP:{tp_str} | SL:{sl_str}")

            # ---------------------------------------------------------
            # 4. ORDEN DE ENTRADA (MARKET)
            # ---------------------------------------------------------
            entry_params = {
                'symbol': symbol,
                'side': side_entry,
                'type': ORDER_TYPE_MARKET,
                'quantity': quantity,
            }
            # En Hedge Mode es obligatorio enviar positionSide
            if self.hedge_mode:
                entry_params['positionSide'] = position_side

            print(f"🚀 Enviando orden MARKET...")
            entry_order = self.client.futures_create_order(**entry_params)
            
            avg_price = float(entry_order.get('avgPrice', ref_price))
            print(f"✅ ENTRADA EJECUTADA: {symbol} @ {avg_price}")

            # ---------------------------------------------------------
            # 5. ORDENES DE SALIDA (TP / SL)
            # ---------------------------------------------------------
            # NOTA SEGÚN DOCUMENTACIÓN:
            # - Para cerrar posición completa se usa closePosition=True (o string 'true').
            # - NO se debe enviar 'quantity' cuando se usa closePosition=True.
            # - El 'type' debe ser STOP_MARKET o TAKE_PROFIT_MARKET.
            
            # -- STOP LOSS --
            sl_params = {
                'symbol': symbol,
                'side': side_exit,
                'type': 'STOP_MARKET',
                'stopPrice': sl_str,
                'closePosition': 'true', # Enviamos string explícito para asegurar compatibilidad
                'workingType': 'MARK_PRICE'
            }
            if self.hedge_mode:
                sl_params['positionSide'] = position_side
            
            try:
                self.client.futures_create_order(**sl_params)
                print(f"   🛡️ SL ({sl_str}) -> OK")
            except BinanceAPIException as e:
                print(f"   ❌ ERROR AL COLOCAR SL: {e.message} (Código: {e.code})")

            # -- TAKE PROFIT --
            tp_params = {
                'symbol': symbol,
                'side': side_exit,
                'type': 'TAKE_PROFIT_MARKET',
                'stopPrice': tp_str,
                'closePosition': 'true',
                'workingType': 'MARK_PRICE'
            }
            if self.hedge_mode:
                tp_params['positionSide'] = position_side

            try:
                self.client.futures_create_order(**tp_params)
                print(f"   💰 TP ({tp_str}) -> OK")
            except BinanceAPIException as e:
                print(f"   ❌ ERROR AL COLOCAR TP: {e.message} (Código: {e.code})")

            print(f"🏁 Proceso terminado para {symbol}")

        except BinanceAPIException as e:
            print(f"❌ ERROR API CRÍTICO en {symbol}: {e.message}")
        except Exception as e:
            print(f"❌ ERROR GENÉRICO en {symbol}: {e}")