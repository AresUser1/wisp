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
import html
from telethon import events
from telethon.tl.custom import Button
from telethon.tl.types import ReplyInlineMarkup
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import RPCError

from utils.loader import register, inline_handler, callback_handler
from handlers.user_commands import _call_inline_bot

WISP_CLOSE_KEY = "close_on_read"
WISP_TEMPLATE_KEY = "close_text_template"
DEFAULT_CLOSE_TEMPLATE = "{name} прочитал(а) секретку."

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

@register("wispcfg")
async def wispcfg_cmd(event):
    """Настройки секреток: что показывать после прочтения.

    Usage:
    {prefix}wispcfg — показать текущие настройки
    {prefix}wispcfg close on|off — менять карточку на "прочитал(а)" после открытия (по умолчанию on)
    {prefix}wispcfg text <шаблон> — свой текст вместо стандартного. Плейсхолдер {name} — кликабельное имя прочитавшего.
    {prefix}wispcfg text reset — вернуть текст по умолчанию
    """
    from utils import database as db
    args = (event.pattern_match.group(1) or "").strip()

    if not args:
        close_on_read = db.get_module_data("wisp", WISP_CLOSE_KEY, default=True)
        template = db.get_module_data("wisp", WISP_TEMPLATE_KEY, default=DEFAULT_CLOSE_TEMPLATE)
        status = "включено ✅" if close_on_read else "выключено ⛔️"
        p = db.get_setting("prefix", default=".")
        return await event.edit(
            "🔐 <b>Настройки секреток (wisp)</b>\n\n"
            f"Замена карточки после прочтения: <b>{status}</b>\n"
            f"Текст после прочтения: <code>{html.escape(template)}</code>\n\n"
            f"<i>{p}wispcfg close on/off — включить/выключить\n"
            f"{p}wispcfg text &lt;шаблон&gt; — свой текст ({{name}} — имя со ссылкой)\n"
            f"{p}wispcfg text reset — вернуть текст по умолчанию</i>",
            parse_mode='html'
        )

    parts = args.split(maxsplit=1)
    sub = parts[0].lower()

    if sub == "close":
        if len(parts) < 2 or parts[1].strip().lower() not in ("on", "off"):
            return await event.edit("❌ Используйте: <code>.wispcfg close on</code> или <code>.wispcfg close off</code>", parse_mode='html')
        value = parts[1].strip().lower() == "on"
        db.set_module_data("wisp", WISP_CLOSE_KEY, value)
        status = "включена" if value else "выключена"
        return await event.edit(f"✅ Замена карточки после прочтения <b>{status}</b>.", parse_mode='html')

    if sub == "text":
        if len(parts) < 2 or not parts[1].strip():
            return await event.edit("❌ Укажите текст шаблона или <code>reset</code>.", parse_mode='html')
        new_text = parts[1].strip()
        if new_text.lower() == "reset":
            db.set_module_data("wisp", WISP_TEMPLATE_KEY, DEFAULT_CLOSE_TEMPLATE)
            return await event.edit("✅ Текст после прочтения сброшен на стандартный.", parse_mode='html')

        db.set_module_data("wisp", WISP_TEMPLATE_KEY, new_text)
        preview = _build_read_notice(new_text, "Вася", 123456789)
        return await event.edit(f"✅ Текст после прочтения обновлён.\n\n<b>Превью:</b> {preview}", parse_mode='html')

    return await event.edit("❌ Неизвестная подкоманда. Используйте <code>close</code> или <code>text</code>.", parse_mode='html')

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

def _build_read_notice(template: str, reader_name: str, user_id: int) -> str:
    """
    HTML-текст, которым заменяется секретка после прочтения.
    {name} в шаблоне подставляется уже кликабельной ссылкой на аккаунт
    прочитавшего, {id} — его числовым ID. Имя экранируем — оно приходит
    от Telegram (first_name/title) и может содержать символы, которые
    поломают HTML-разметку при parse_mode='html'.

    Если в шаблоне опечатка в плейсхолдере (например, одиночная "{"),
    откатываемся на стандартный текст, а не роняем хендлер.
    """
    safe_name = html.escape(reader_name)
    name_link = f'<a href="tg://user?id={user_id}">{safe_name}</a>'
    try:
        return template.format(name=name_link, id=user_id)
    except (KeyError, IndexError, ValueError):
        return f'{name_link} прочитал(а) секретку.'


@callback_handler(r"wisp_read:(.+)", unrestricted=True)
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

    if u_id != r_id and u_id != s_id:
        return await event.answer(f"🔒 Это сообщение не для вас!\n(Ваш ID: {u_id}, ожидался: {r_id})", alert=True)

    # Если секретка уже прочитана — показываем кто прочитал, секрет не раскрываем повторно.
    if data.get("read"):
        _reader = data.get("reader_name", f"ID {data.get('read_by', '?')}")
        return await event.answer(f"✅ Секретку уже прочитал(а) {_reader}", alert=False)

    # Показываем секрет отправителю или получателю (первое нажатие)
    await event.answer(text, alert=True)

    # Карточку меняем ТОЛЬКО когда читает получатель, не отправитель.
    if u_id != r_id:
        return

    # Поведение после прочтения — если пользователь выключил замену карточки,
    # ничего не трогаем.
    close_on_read = db.get_module_data("wisp", WISP_CLOSE_KEY, default=True)
    if not close_on_read:
        return

    reader_name = f"ID {u_id}"
    try:
        reader = await event.get_sender()
        reader_name = getattr(reader, "first_name", None) or getattr(reader, "title", None) or reader_name
    except Exception:
        pass

    # Сохраняем имя для повторных кликов на "✅ Прочитано"
    data["read"] = True
    data["read_by"] = u_id
    data["reader_name"] = reader_name
    db.set_module_data("wisp", f"msg_{wisp_id}", data)

    template = db.get_module_data("wisp", WISP_TEMPLATE_KEY, default=DEFAULT_CLOSE_TEMPLATE)
    closed_text = _build_read_notice(template, reader_name, u_id)

    # Правим карточку через EditInlineBotMessageRequest напрямую.
    # Получаем InputBotInlineMessageID через original_update — надёжный путь,
    # который использует bot_callbacks.py (_HtmlCallProxy.edit / delete).
    #
    # Кнопку убираем не передавая reply_markup вообще (flag.2 не выставляется).
    # Telegram при замене текста без reply_markup убирает inline-клавиатуру.
    # ReplyInlineMarkup(rows=[]) явно отклоняется сервером (REPLY_MARKUP_INVALID),
    # поэтому единственный рабочий способ — опустить поле целиком.
    try:
        from telethon import functions as _tl_f
        from telethon.extensions import html as _tl_html
        from telethon.tl.types import ReplyKeyboardHide as _RKH

        # InputBotInlineMessageID через original_update (как в bot_callbacks.py)
        _raw = getattr(event, "original_update", None)
        _iid = None
        if _raw is not None and type(_raw).__name__ == "UpdateInlineBotCallbackQuery":
            _iid = getattr(_raw, "msg_id", None)
        if _iid is None:
            _q = getattr(event, "query", None)
            if _q is not None:
                _iid = getattr(_q, "msg_id", None)
        if _iid is None:
            _iid = getattr(event, "inline_message_id", None)

        if _iid is not None:
            _msg_text, _entities = _tl_html.parse(closed_text)
            # Попытка 1: reply_markup не передаём — Telegram убирает кнопки
            # при замене текста без явной клавиатуры.
            _req = _tl_f.messages.EditInlineBotMessageRequest(
                id=_iid,
                message=_msg_text,
                entities=_entities,
                no_webpage=True,
            )
            try:
                await event.client(_req)
            except Exception as _e1:
                import logging as _wlog
                _wlog.getLogger("wisp").warning(f"[wisp_read] edit pass1 failed: {_e1}")
                # Попытка 2: ReplyKeyboardHide — говорит серверу убрать клавиатуру
                try:
                    _req2 = _tl_f.messages.EditInlineBotMessageRequest(
                        id=_iid,
                        message=_msg_text,
                        entities=_entities,
                        reply_markup=_RKH(),
                        no_webpage=True,
                    )
                    await event.client(_req2)
                except Exception as _e2:
                    _wlog.getLogger("wisp").warning(f"[wisp_read] edit pass2 failed: {_e2}")
    except Exception as _edit_err:
        import logging as _wlog
        _wlog.getLogger("wisp").warning(f"[wisp_read] edit_inline failed: {_edit_err}")

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
