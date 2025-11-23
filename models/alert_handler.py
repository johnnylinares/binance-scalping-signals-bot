import telegram
import os
from telegram import Message

from dotenv import load_dotenv

load_dotenv()

bot = telegram.Bot(token=os.getenv("BOT_TOKEN"))

async def alert_handler(symbol, percentage_change, price, emoji, volume):
    vol_rnd = round(volume / 1000000, 2)


    msg : Message = await bot.send_message(
        chat_id=os.getenv("CHANNEL_ID"),
        text=f'{emoji[0]} #{symbol} {emoji[1]} {percentage_change:+.2f}%\n💵 ${price} 💰 ${vol_rnd}M'
    )
    print(f"{symbol} alert sended.")
    return msg.message_id


async def tp_sl_alert_handler(hit, result, close_price, original_message_id):
    if hit == -1:
        alert = f"❌ SL ({result}% [{close_price}])"
    elif hit == 0:
        alert = f"➖ CERRADA ({result}% [{close_price}])"
    elif hit == 1:
        alert = f"✅ TP1 (+{result}% [{close_price}])"
    elif hit == 2:
        alert = f"✅ TP2 (+{result}% [{close_price}])"
    elif hit == 3:
        alert = f"✅ TP3 (+{result}% [{close_price}])"
    elif hit == 4:
        alert = f"✅ TP4 (+{result}% [{close_price}])"

    await bot.send_message(
        chat_id=os.getenv("CHANNEL_ID"),

        text=f'{alert}',
        reply_to_message_id=original_message_id
    )
