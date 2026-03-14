import time
import hmac
import hashlib
import urllib.parse
import requests
from decimal import Decimal, ROUND_DOWN
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from config.settings import DEMO_API_KEY, DEMO_API_SECRET

class OperationHandler:
    def __init__(self):
        self.api_key = DEMO_API_KEY
        self.secret_key = DEMO_API_SECRET
        self.hedge_mode = False
        self.base_url = "https://testnet.binancefuture.com"
        
        try:
            self.client = Client(self.api_key, self.secret_key, testnet=True)
            print("🤖 OperationHandler: Connected to Binance Futures TESTNET.")
            self._check_position_mode()
        except Exception as e:
            print(f"⚠️ OperationHandler: Error connecting to Binance: {e}")

    def _check_position_mode(self):
        try:
            info = self.client.futures_get_position_mode()
            self.hedge_mode = info['dualSidePosition']
            mode = "HEDGE MODE" if self.hedge_mode else "ONE-WAY MODE"
            print(f"ℹ️ Detected mode: {mode}")
        except Exception as e:
            self.hedge_mode = False
            print(f"⚠️ Error getting position mode: {e}. Assuming One-Way.")

    def _ensure_isolated_margin(self, symbol):
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
            print(f"✅ {symbol}: ISOLATED margin set.")
        except BinanceAPIException as e:
            if e.code != -4046:
                print(f"⚠️ Margin warning {symbol}: {e.message}")
        except Exception as e:
            print(f"⚠️ Error setting margin: {e}")

    def _set_leverage(self, symbol, leverage):
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            print(f"⚙️ {symbol}: Leverage {leverage}x set.")
        except BinanceAPIException as e:
            if e.code != -4046:
                print(f"⚠️ Leverage warning {symbol}: {e.message}")
        except Exception as e:
            print(f"⚠️ Error setting leverage: {e}")

    def _get_symbol_filters(self, symbol):
        try:
            info = self.client.futures_exchange_info()
            tick_size = None
            step_size = None
            price_precision = 2
            qty_precision = 3

            for s in info['symbols']:
                if s['symbol'] == symbol:
                    price_precision = s['pricePrecision']
                    qty_precision = s['quantityPrecision']
                    for f in s['filters']:
                        if f['filterType'] == 'PRICE_FILTER':
                            tick_size = float(f['tickSize'])
                        elif f['filterType'] == 'LOT_SIZE':
                            step_size = float(f['stepSize'])
                    break
            
            if tick_size is None:
                tick_size = 1 / (10**price_precision)
            if step_size is None:
                step_size = 1 / (10**qty_precision)

            return price_precision, qty_precision, tick_size, step_size
        except Exception as e:
            print(f"⚠️ Error getting filters {symbol}: {e}")
            return 2, 3, 0.01, 0.001

    def _round_to_step(self, value, step, precision):
        value_dec = Decimal(str(value))
        step_dec = Decimal(str(step))
        rounded = (value_dec / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
        fmt = "{:." + str(precision) + "f}"
        return fmt.format(rounded)

    def _place_algo_order_manual(self, **params):
        endpoint = "/fapi/v1/algoOrder"
        
        params['timestamp'] = int(time.time() * 1000)
        clean_params = {k: v for k, v in params.items() if v is not None}
        
        query_string = urllib.parse.urlencode(clean_params)
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {'X-MBX-APIKEY': self.api_key}
        full_params = clean_params.copy()
        full_params['signature'] = signature
        
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, headers=headers, params=full_params)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise BinanceAPIException(
                response.status_code,
                response.status_code,
                response.text
            )

    def _place_algo_order(self, **params):
        params['algoType'] = 'CONDITIONAL'
        
        if hasattr(self.client, 'futures_create_algo_order'):
            return self.client.futures_create_algo_order(**params)
        
        return self._place_algo_order_manual(**params)

    def process_new_signal(self, signal_data):
        symbol = signal_data.get('symbol')
        signal_direction = signal_data.get('direction')
        ref_price = float(signal_data.get('price', 0))

        if not symbol or ref_price == 0:
            return

        print(f"⚡ PROCESSING SIGNAL: {symbol} | Dir: {signal_direction}")

        self._ensure_isolated_margin(symbol)
        self._set_leverage(symbol, 10)

        if signal_direction == "LONG":
            side_entry = SIDE_BUY
            side_exit = SIDE_SELL
            position_side = 'LONG' if self.hedge_mode else None
            tp_pct, sl_pct = 0.10, 0.05
            raw_tp = ref_price * (1 + tp_pct)
            raw_sl = ref_price * (1 - sl_pct)
        else:
            side_entry = SIDE_SELL
            side_exit = SIDE_BUY
            position_side = 'SHORT' if self.hedge_mode else None
            tp_pct, sl_pct = 0.10, 0.05
            raw_tp = ref_price * (1 - tp_pct)
            raw_sl = ref_price * (1 + sl_pct)

        try:
            p_prec, q_prec, tick_size, step_size = self._get_symbol_filters(symbol)
            position_size_usdt = 100.0
            raw_qty = position_size_usdt / ref_price
            
            qty_str = self._round_to_step(raw_qty, step_size, q_prec)
            tp_str = self._round_to_step(raw_tp, tick_size, p_prec)
            sl_str = self._round_to_step(raw_sl, tick_size, p_prec)

            print(f"📝 PLAN: Qty:{qty_str} | TP:{tp_str} | SL:{sl_str}")

            entry_params = {
                'symbol': symbol,
                'side': side_entry,
                'type': ORDER_TYPE_MARKET,
                'quantity': qty_str,
            }
            if position_side:
                entry_params['positionSide'] = position_side

            print(f"🚀 Sending ENTRY order...")
            entry_order = self.client.futures_create_order(**entry_params)
            avg_price = float(entry_order.get('avgPrice', ref_price))
            print(f"✅ ENTRY executed @ {avg_price}")

            time.sleep(1.5)

            common_algo_params = {
                'symbol': symbol,
                'side': side_exit,
                'closePosition': 'true',
                'workingType': 'MARK_PRICE',
                'priceProtect': 'TRUE'
            }
            if position_side:
                common_algo_params['positionSide'] = position_side

            try:
                sl_params = common_algo_params.copy()
                sl_params['type'] = 'STOP_MARKET'
                sl_params['triggerPrice'] = sl_str
                
                self._place_algo_order(**sl_params)
                print(f"   🛡️ SL placed at {sl_str}")
            except Exception as e:
                print(f"   ❌ SL error: {e}")

            try:
                tp_params = common_algo_params.copy()
                tp_params['type'] = 'TAKE_PROFIT_MARKET'
                tp_params['triggerPrice'] = tp_str
                
                self._place_algo_order(**tp_params)
                print(f"   💰 TP placed at {tp_str}")
            except Exception as e:
                print(f"   ❌ TP error: {e}")

            print(f"🏁 Completed {symbol}")

        except BinanceAPIException as e:
            print(f"❌ API ERROR ({symbol}): {e.message} Code:{e.code}")
        except Exception as e:
            print(f"❌ GENERAL ERROR ({symbol}): {e}")