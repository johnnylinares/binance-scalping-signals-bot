import telegram
from telegram import Message
from telegram.error import TelegramError
from config.settings import BOT_TOKEN, CHANNEL_ID, GROUP_ID

bot = telegram.Bot(BOT_TOKEN)

try:
    _GROUP_ID_INT = int(GROUP_ID)
except (TypeError, ValueError):
    _GROUP_ID_INT = None

_last_update_id: Optional[int] = None
_discussion_message_map: Dict[int, Message] = {}


async def _find_discussion_message(channel_message: Message, timeout: float = 6.0) -> Optional[Message]:
    """Locate the mirrored discussion message for the given channel post."""
    global _last_update_id

    deadline = asyncio.get_running_loop().time() + timeout
    offset = _last_update_id

    while asyncio.get_running_loop().time() < deadline:
        remaining = max(0, int(deadline - asyncio.get_running_loop().time())) or 1
        try:
            updates = await bot.get_updates(offset=offset, timeout=remaining)
        except TelegramError as exc:
            print(f"[alert_handler] Failed to fetch updates: {exc}")
            return None

        for update in updates:
            offset = update.update_id + 1
            _last_update_id = offset

            message = update.message
            if message is None:
                continue

            if _GROUP_ID_INT is not None and message.chat_id != _GROUP_ID_INT:
                continue

            if not getattr(message, "is_automatic_forward", False):
                continue

            if (
                message.forward_from_chat
                and message.forward_from_chat.id == channel_message.chat_id
                and message.forward_from_message_id == channel_message.message_id
            ):
                return message

        await asyncio.sleep(0.3)

    return None


async def alert_handler(symbol, percentage_change, price, emoji, volume):
    vol_rnd = round(volume / 1000000, 2)

    msg : Message = await bot.send_message(
        chat_id = CHANNEL_ID,
        text=f'{emoji[0]} #{symbol} {emoji[1]} {percentage_change:+.2f}%\n💵 ${price} 💰 ${vol_rnd}M'
    )

    discussion_message = await _find_discussion_message(msg)
    if discussion_message is not None:
        _discussion_message_map[msg.message_id] = discussion_message
    else:
        print(f"[alert_handler] Discussion message not found for {msg.message_id}")

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

    discussion_message = _discussion_message_map.get(original_message_id)

    send_kwargs = {
        "chat_id": GROUP_ID,
        "text": f"{alert}",
        "allow_sending_without_reply": True,
    }

    if discussion_message is not None:
        send_kwargs["reply_to_message_id"] = discussion_message.message_id

        thread_id = getattr(discussion_message, "message_thread_id", None)
        if thread_id is not None:
            send_kwargs["message_thread_id"] = thread_id

    await bot.send_message(**send_kwargs)
