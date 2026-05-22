import asyncio
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest

BOT_TOKEN = "8828482180:AAE_Sdrqk5O5USAWpsShd2jetGt099J-Jso"
EXCHANGE_API_KEY = "67d1275a636192e890d24d79"
CHECK_INTERVAL = 60
PROXY = "socks5://194.147.148.43:12880"

PAIRS = {
    "EUR/USD": ("EUR", "USD"),
    "GBP/USD": ("GBP", "USD"),
    "USD/JPY": ("USD", "JPY"),
    "USD/CHF": ("USD", "CHF"),
    "AUD/USD": ("AUD", "USD"),
    "USD/CAD": ("USD", "CAD"),
    "NZD/USD": ("NZD", "USD"),
    "EUR/GBP": ("EUR", "GBP"),
    "BTC/USD": ("BTC", "USD"),
    "ETH/USD": ("ETH", "USD"),
}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

user_alerts: dict[int, dict[str, dict]] = {}
user_subscriptions: dict[int, set] = {}

def get_rate(base, quote):
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/{base}/{quote}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("result") == "success":
            return round(data["conversion_rate"], 5)
    except Exception as e:
        logger.error(f"Ошибка курса {base}/{quote}: {e}")
    return None

def pairs_keyboard(user_id):
    subs = user_subscriptions.get(user_id, set())
    buttons = []
    row = []
    for pair in PAIRS:
        mark = "✅ " if pair in subs else ""
        row.append(InlineKeyboardButton(f"{mark}{pair}", callback_data=f"toggle_{pair}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("📋 Мои алерты", callback_data="my_alerts")])
    return InlineKeyboardMarkup(buttons)

def alert_keyboard(pair):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Выше цены", callback_data=f"set_above_{pair}"),
         InlineKeyboardButton("📉 Ниже цены", callback_data=f"set_below_{pair}")],
        [InlineKeyboardButton("🗑 Удалить алерты", callback_data=f"del_alerts_{pair}")],
        [InlineKeyboardButton("← Назад", callback_data="back_pairs")],
    ])

async def cmd_start(update, ctx):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\nВыбери пары 👇",
        reply_markup=pairs_keyboard(user.id)
    )

async def cmd_pairs(update, ctx):
    await update.message.reply_text("📊 Выбери валютные пары:", reply_markup=pairs_keyboard(update.effective_user.id))

async def cmd_rates(update, ctx):
    uid = update.effective_user.id
    subs = user_subscriptions.get(uid, set())
    if not subs:
        await update.message.reply_text("Не подписан ни на одну пару. /pairs")
        return
    lines = ["📈 *Текущие курсы:*\n"]
    for pair in subs:
        base, quote = PAIRS[pair]
        rate = get_rate(base, quote)
        lines.append(f"`{pair}` → {rate if rate else '—'}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_alerts(update, ctx):
    uid = update.effective_user.id
    alerts = user_alerts.get(uid, {})
    if not alerts:
        await update.message.reply_text("Нет активных алертов. /pairs")
        return
    lines = ["🔔 *Активные алерты:*\n"]
    for pair, lvls in alerts.items():
        above = f"выше {lvls['above']}" if lvls.get("above") else None
        below = f"ниже {lvls['below']}" if lvls.get("below") else None
        parts = ", ".join(filter(None, [above, below]))
        lines.append(f"`{pair}` — {parts}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def on_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("toggle_"):
        pair = data[7:]
        subs = user_subscriptions.setdefault(uid, set())
        if pair in subs:
            subs.discard(pair)
            await query.edit_message_text(f"❌ Отписался от {pair}\n\nВыбери пары:", reply_markup=pairs_keyboard(uid))
        else:
            subs.add(pair)
            base, quote = PAIRS[pair]
            rate = get_rate(base, quote)
            rate_str = f"\nТекущий курс: *{rate}*" if rate else ""
            await query.edit_message_text(
                f"✅ Подписался на {pair}{rate_str}\n\nНажми на пару ещё раз для алерта:",
                parse_mode="Markdown", reply_markup=pairs_keyboard(uid)
            )
    elif data.startswith("set_above_") or data.startswith("set_below_"):
        direction = "above" if "set_above" in data else "below"
        pair = data.replace("set_above_", "").replace("set_below_", "")
        ctx.user_data["awaiting_price"] = {"pair": pair, "direction": direction}
        emoji = "📈" if direction == "above" else "📉"
        await query.edit_message_text(
            f"{emoji} Введи цену для алерта по *{pair}*\n_(например: 1.0850)_",
            parse_mode="Markdown"
        )
    elif data.startswith("del_alerts_"):
        pair = data[11:]
        user_alerts.get(uid, {}).pop(pair, None)
        await query.edit_message_text(f"🗑 Алерты по {pair} удалены.", reply_markup=pairs_keyboard(uid))
    elif data == "my_alerts":
        alerts = user_alerts.get(uid, {})
        if not alerts:
            await query.edit_message_text("Нет активных алертов.", reply_markup=pairs_keyboard(uid))
        else:
            lines = ["🔔 *Активные алерты:*\n"]
            for pair, lvls in alerts.items():
                above = f"↑ {lvls['above']}" if lvls.get("above") else None
                below = f"↓ {lvls['below']}" if lvls.get("below") else None
                lines.append(f"`{pair}` {'  '.join(filter(None, [above, below]))}")
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=pairs_keyboard(uid))
    elif data == "back_pairs":
        await query.edit_message_text("📊 Выбери валютные пары:", reply_markup=pairs_keyboard(uid))

async def on_message(update, ctx):
    awaiting = ctx.user_data.get("awaiting_price")
    if not awaiting:
        await update.message.reply_text("Используй /pairs чтобы начать.")
        return
    try:
        price = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введи число, например: 1.0850")
        return
    uid = update.effective_user.id
    pair = awaiting["pair"]
    direction = awaiting["direction"]
    user_alerts.setdefault(uid, {}).setdefault(pair, {})
    user_alerts[uid][pair][direction] = price
    ctx.user_data.pop("awaiting_price", None)
    emoji = "📈" if direction == "above" else "📉"
    dir_ru = "выше" if direction == "above" else "ниже"
    await update.message.reply_text(
        f"✅ Алерт установлен!\n{emoji} {pair} {dir_ru} *{price}*",
        parse_mode="Markdown", reply_markup=pairs_keyboard(uid)
    )

async def check_prices(app):
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        for uid, alerts in list(user_alerts.items()):
            for pair, levels in list(alerts.items()):
                if not levels:
                    continue
                base, quote = PAIRS[pair]
                rate = get_rate(base, quote)
                if rate is None:
                    continue
                triggered = []
                if levels.get("above") and rate >= levels["above"]:
                    triggered.append(f"📈 Цена *выше* уровня {levels['above']} → текущая: *{rate}*")
                    levels.pop("above")
                if levels.get("below") and rate <= levels["below"]:
                    triggered.append(f"📉 Цена *ниже* уровня {levels['below']} → текущая: *{rate}*")
                    levels.pop("below")
                for msg in triggered:
                    try:
                        await app.bot.send_message(chat_id=uid, text=f"🔔 *Алерт {pair}!*\n{msg}", parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Ошибка алерта: {e}")

def main():
    request = HTTPXRequest(proxy=PROXY)
    app = Application.builder().token(BOT_TOKEN).request(request).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pairs", cmd_pairs))
    app.add_handler(CommandHandler("rates", cmd_rates))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CallbackQueryHandler(on_callback))
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(app))
    logger.info("Бот запущен через прокси...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
