# modules/wisp.py
"""
<manifest>
version: 1.0.4
source: https://raw.githubusercontent.com/AresUser1/wisp/main/wisp.py
author: SynForge
</manifest>

Модуль для отправки секретных сообщений.
"""

import uuid
import re
from telethon import events
from telethon.tl.custom import Button
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import RPCError

from utils.loader import register, inline_handler, callback_handler
from handlers.user_commands import _call_inline_bot

@register("wisp")
async def wisp_cmd(event):
    """Отправить секретное сообщение.
    
    Usage: {prefix}wisp <id/username> <текст>
    Инлайн: @bot wisp <id/username> <текст>
    """
    args = event.pattern_match.group(1)
    if not args:
        return await event.edit("❌ <b>Использование:</b> <code>.wisp <id/username> <текст></code>", parse_mode='html')

    # Регулярка для разделения получателя и текста
    match = re.match(r"^(\d+|@\w+)\s+(.*)", args, re.DOTALL)
    if not match:
        return await event.edit("❌ <b>Неверный формат.</b>\nПример: <code>.wisp @user привет</code>", parse_mode='html')

    target = match.group(1)
    message_text = match.group(2).strip()

    if not message_text:
        return await event.edit("❌ <b>Введите текст сообщения.</b>", parse_mode='html')

    # Лимит answerCallbackQuery — 200 байт UTF-8.
    # Русский текст ~2 байта/символ, поэтому реальный лимит ~100 кириллических символов.
    msg_bytes = len(message_text.encode('utf-8'))
    if msg_bytes > 200:
        over = msg_bytes - 200
        msg = (
            "❌ <b>Текст слишком длинный!</b>\n"
            f"Лимит: <b>200 байт</b>, у вас: <b>{msg_bytes}</b> (+{over} лишних).\n"
            "<i>Совет: ~100 кириллических или ~200 латинских символов.</i>"
        )
        return await event.edit(msg, parse_mode='html')

    if not event.client.bot_client:
        return await event.edit("❌ <b>Бот-помощник не подключен!</b>", parse_mode='html')

    # МГНОВЕННО затираем секрет в чате, чтобы анти-удалялки видели только это
    try:
        bot_info = await event.client.bot_client.get_me()
        bot_username = bot_info.username
    except:
        bot_username = "bot"

    wisp_id = str(uuid.uuid4())[:8]
    await event.edit(f"@{bot_username} wisp:{wisp_id}")

    recipient_id = 0
    recipient_name = target

    # 1. Проверяем на ID
    clean_target = target.lstrip("-")
    if clean_target.isdigit():
        recipient_id = int(target)
        try:
            user = await event.client.get_entity(recipient_id)
            recipient_name = user.first_name or f"ID: {recipient_id}"
        except:
            recipient_name = f"ID: {target}"
    else:
        # 2. Пробуем как юзернейм
        try:
            user = await event.client.get_entity(target)
            recipient_id = int(user.id)
            recipient_name = user.first_name or target
        except Exception as e:
            return await event.edit(f"❌ <b>Пользователь '{target}' не найден.</b>", parse_mode='html')

    sender_id = (await event.client.get_me()).id

    from utils import database as db
    db.set_module_data("wisp", f"msg_{wisp_id}", {
        "text": message_text,
        "recipient_id": int(recipient_id),
        "sender_id": int(sender_id),
        "recipient_name": recipient_name
    })

    query = f"wisp:{wisp_id}"
    await _call_inline_bot(event, query)

@inline_handler(r"wisp:(.+)", title="Секретное сообщение", description="Отправить секретку")
async def wisp_inline(event):
    wisp_id = event.pattern_match.group(1)
    from utils import database as db
    data = db.get_module_data("wisp", f"msg_{wisp_id}")

    if not data:
        return "❌ Сообщение не найдено", []

    recipient_name = data.get("recipient_name", "Пользователь")
    
    text = f"🔐 <b>Секретное сообщение для {recipient_name}</b>\n\n<i>Прочитать его может только получатель и отправитель.</i>"
    buttons = [
        [Button.inline("📥 Прочитать сообщение", data=f"wisp_read:{wisp_id}")]
    ]
    
    return text, buttons

@callback_handler(r"wisp_read:(.+)")
async def wisp_read_callback(event):
    wisp_id = event.pattern_match.group(1)
    from utils import database as db
    data = db.get_module_data("wisp", f"msg_{wisp_id}")

    if not data:
        return await event.answer("❌ Сообщение больше не доступно.", alert=True)

    recipient_id = data.get("recipient_id")
    sender_id = data.get("sender_id")
    text = data.get("text")
    
    user_id = event.sender_id

    # Принудительно приводим всё к int для корректного сравнения
    try:
        u_id = int(user_id)
        r_id = int(recipient_id)
        s_id = int(sender_id)
    except (ValueError, TypeError):
        return await event.answer("❌ Ошибка данных сообщения.", alert=True)

    if u_id == r_id or u_id == s_id:
        await event.answer(text, alert=True)
    else:
        await event.answer(f"🔒 Это сообщение не для вас!\n(Ваш ID: {u_id}, ожидался: {r_id})", alert=True)

@inline_handler(r"wisp\s+(\S+)\s+(.*)", title="🔐 Отправить секретку", description="Используйте: wisp <id/user> <текст>")
async def wisp_create_inline(event):
    from utils import database as db
    sender_id = int(event.sender_id)
    
    # Секретки могут отправлять все, если это не запрещено глобально
    # Но для безопасности оставим проверку OWNER/TRUSTED для СОЗДАНИЯ через инлайн
    if db.get_user_level(sender_id) not in ["OWNER", "TRUSTED"]:
        return "🚫 Создание секреток через инлайн доступно только доверенным пользователям.", [[Button.url("🐾 KoteLoader", "https://t.me/KoteLoader")]]

    target = event.pattern_match.group(1).strip()
    message_text = event.pattern_match.group(2).strip()
    
    if not message_text:
        return "❌ Введите текст", []

    msg_bytes = len(message_text.encode('utf-8'))
    if msg_bytes > 200:
        over = msg_bytes - 200
        return (
            f"❌ Текст слишком длинный! Лимит: 200 байт, у вас: {msg_bytes} (+{over} лишних). Совет: ~100 кириллических или ~200 латинских символов.",
            []
        )

    recipient_id = 0
    recipient_name = target

    # 1. Проверяем, не является ли target чистым ID (числа или -100...)
    clean_target = target.lstrip("-")
    if clean_target.isdigit():
        recipient_id = int(target)
        # Пытаемся получить имя для красоты, если не выйдет - оставим ID
        try:
            user = await event.client.get_entity(recipient_id)
            recipient_name = user.first_name or f"ID: {recipient_id}"
        except:
            recipient_name = f"ID: {target}"
    else:
        # 2. Если это не ID, пробуем как юзернейм/сущность
        try:
            user = await event.client.get_entity(target)
            recipient_id = int(user.id)
            recipient_name = user.first_name or target
        except:
            return f"❌ Пользователь '{target}' не найден.", []

    wisp_id = str(uuid.uuid4())[:8]

    db.set_module_data("wisp", f"msg_{wisp_id}", {
        "text": message_text,
        "recipient_id": int(recipient_id),
        "sender_id": int(sender_id),
        "recipient_name": recipient_name
    })

    text = f"🔐 <b>Секретное сообщение для {recipient_name}</b>\n\n<i>Прочитать его может только получатель и отправитель.</i>"
    buttons = [[Button.inline("📥 Прочитать сообщение", data=f"wisp_read:{wisp_id}")]]
    
    return text, buttons
