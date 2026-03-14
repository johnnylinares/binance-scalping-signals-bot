import telegram
from telegram import Message
from config.settings import BOT_TOKEN, CHANNEL_ID, GROUP_ID

bot = telegram.Bot(BOT_TOKEN)

async def alert_handler(symbol, percentage_change, price, emoji, volume):
    vol_rnd = round(volume / 1000000, 2)

    msg : Message = await bot.send_message(
        chat_id = CHANNEL_ID,
        text=f'{emoji[0]} #{symbol} {emoji[1]} {percentage_change:+.2f}%\n💵 ${price} 💰 ${vol_rnd}M'
    )
    print(f"{symbol} alert sended.")
    return msg.message_id

async def tp_sl_alert_handler(hit, result, original_message_id):
    if hit == -1:
        alert = f"❌ SL (-5%)"
    elif hit == 0:
        alert = f"➖ CERRADA (+{result}%)" if result > 0 else f"➖ CERRADA ({result}%)"
    elif hit == 1:
        alert = f"✅ TP1 (+5%)"
    elif hit == 2:
        alert = f"✅ TP2 (+10%)"
    elif hit == 3:
        alert = f"✅ TP3 (+15%)"
    elif hit == 4:
        alert = f"✅ TP4 (+20%)"

    await bot.send_message(
        chat_id = GROUP_ID,

        text=f'{alert}',
        reply_to_message_id=original_message_id
    )
