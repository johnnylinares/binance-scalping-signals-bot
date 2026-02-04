from supabase import create_client, Client
from models.log_handler import log
from config.settings import SUPABASE_URL, SUPABASE_KEY

supabase: Client = None

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("[DB_HANDLER] Conexión con Supabase creada.")
except Exception as e:
    print(f"[DB_HANDLER] ERROR al crear cliente de Supabase: {e}")

async def insert_trade(trade_data: dict):
    """
    Inserta un trade COMPLETO en la base de datos.
    """
    if supabase is None:
        await log("[DB_HANDLER] ERROR: Supabase client no está inicializado.")
        return

    try:
        response = supabase.table('signals-data').insert(trade_data).execute()
        
        if response.data:
            await log(f"[DB_HANDLER] Trade insertado: {trade_data.get('symbol')} -> {trade_data.get('result')}%")
        else:
            await log(f"[DB_HANDLER] WARNING: Respuesta vacía al insertar trade de {trade_data.get('symbol')}")
        
    except Exception as e:
        await log(f"[DB_HANDLER] ERROR al insertar trade: {e} | Data: {trade_data}")