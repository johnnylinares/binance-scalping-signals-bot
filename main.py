import asyncio
import threading
import os

from datetime import datetime
from flask import Flask, jsonify
from binance import AsyncClient

from models.coin_handler import coin_handler
from models.log_handler import log

async def binance_client():
    client = await AsyncClient.create(
        api_key=os.getenv("API_KEY"), 
        api_secret=os.getenv("API_SECRET")
    )

    await log("🟢 Binance client created sucessfully.")
    return client

async def main():
    await log("🟢 Bot started.")

    client = None
    try:
        client = await binance_client()

        while True:
            try:
                await log("🔄 Iniciando ciclo de tracking de precios...")
                
                wait_seconds = 6 * 60 * 60
            
                try:
                    await asyncio.wait_for(
                        coin_handler(client, wait_seconds),
                        timeout=wait_seconds + 60 
                    )
                except asyncio.TimeoutError:
                    await log("⏰ Timeout reached. Restarting price tracking...")
                
                await log("🔄 Cycle completed. Updating coin list...")
                
            except Exception as e:
                await log(f"[ERROR] Error in tracking cycle: {e}")
                await log("[RETRY] Waiting 60 seconds before retrying...")
                await asyncio.sleep(60)

    except Exception as e:
        await log(f"[ERROR] Error in main: {e}")
    finally:
        if client:
            await client.close_connection()
            await log("[CLIENT] Binance client closed.")

def run_bot():
    asyncio.run(main())

def keep_bot():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    return bot_thread

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "active", "message": "Binance/Telegram Bot Running"})

@app.route('/ping')
def ping():
    return jsonify({"status": "ok"}), 200

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "binance-telegram-bot",
        "timestamp": datetime.now().isoformat()
    }), 200

if __name__ == "__main__":
    bot_thread = keep_bot()
    
    port = int(os.getenv("PORT", 8000))
    app.run(host='0.0.0.0', port=port)