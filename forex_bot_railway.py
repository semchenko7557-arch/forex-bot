import asyncio
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8828482180:AAE_Sdrqk5O5USAWpsShd2jetGt099J-Jso"
ALPHA_API_KEY = "3Q5QBKUEZZ7JFTA7"
CHECK_INTERVAL = 60

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
user_journal: dict[int, list] = {}        # торговый журнал
user_settings: dict[int, dict] = {}       # настройки (депозит, риск)
user_diary: dict[int, list] = {}          # психологический дневник

# ─── API ──────────────────────────────────────────────────────────────────────

def get_rate(base, quote):
    try:
        url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_API_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()
        rate_data = data.get("Realtime Currency Exchange Rate", {})
        if rate_data:
            return round(float(rate_data["5. Exchange Rate"]), 5)
    except Exception as e:
        logger.error(f"Ошибка курса {base}/{quote}: {e}")
    return None

def get_news():
    try:
        url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=forex&apikey={ALPHA_API_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()
        items = data.get("feed", [])[:5]
        return items
    except Exception as e:
        logger.error(f"Ошибка новостей: {e}")
    return []

# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Котировки и алерты", callback_data="menu_pairs"),
         InlineKeyboardButton("📰 Новости", callback_data="menu_news")],
        [InlineKeyboardButton("📒 Журнал сделок", callback_data="menu_journal"),
         InlineKeyboardButton("🧮 Калькулятор риска", callback_data="menu_risk")],
        [InlineKeyboardButton("🧠 Дневник психологии", callback_data="menu_diary"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
    ])

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
    buttons.append([InlineKeyboardButton("← Меню", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def alert_keyboard(pair):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Выше цены", callback_data=f"set_above_{pair}"),
         InlineKeyboardButton("📉 Ниже цены", callback_data=f"set_below_{pair}")],
        [InlineKeyboardButton("🗑 Удалить алерты", callback_data=f"del_alerts_{pair}")],
        [InlineKeyboardButton("❌ Отписаться", callback_data=f"unsub_{pair}")],
        [InlineKeyboardButton("← Назад", callback_data="back_pairs")],
    ])

def journal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить сделку", callback_data="journal_add")],
        [InlineKeyboardButton("📊 Статистика", callback_data="journal_stats")],
        [InlineKeyboardButton("📋 Последние 10", callback_data="journal_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

def risk_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧮 Рассчитать лот", callback_data="risk_calc")],
        [InlineKeyboardButton("💰 Установить депозит", callback_data="risk_deposit")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

def diary_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Добавить запись", callback_data="diary_add")],
        [InlineKeyboardButton("📖 Последние записи", callback_data="diary_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

# ─── Команды ──────────────────────────────────────────────────────────────────

async def cmd_start(update, ctx):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        "Я твой торговый помощник. Выбери раздел 👇",
        reply_markup=main_keyboard()
    )

async def cmd_menu(update, ctx):
    await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())

# ─── Обработчик сообщений ─────────────────────────────────────────────────────

async def on_message(update, ctx):
    uid = update.effective_user.id
    text = update.message.text
    state = ctx.user_data.get("state")

    # Алерт — ввод цены
    if state == "awaiting_price":
        awaiting = ctx.user_data.get("awaiting_price")
        try:
            price = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ Введи число, например: 1.0850")
            return
        pair = awaiting["pair"]
        direction = awaiting["direction"]
        user_alerts.setdefault(uid, {}).setdefault(pair, {})
        user_alerts[uid][pair][direction] = price
        ctx.user_data.pop("state", None)
        ctx.user_data.pop("awaiting_price", None)
        emoji = "📈" if direction == "above" else "📉"
        dir_ru = "выше" if direction == "above" else "ниже"
        await update.message.reply_text(
            f"✅ Алерт установлен!\n{emoji} {pair} {dir_ru} *{price}*",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )

    # Журнал — добавление сделки
    elif state == "journal_add":
        # Формат: EURUSD buy 1.1000 1.0950 1.1100
        # пара, направление, вход, стоп, тейк
        parts = text.strip().split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Неверный формат. Введи:\n`EURUSD buy 1.1000 1.0950 1.1100`\n(пара, направление, вход, стоп-лосс, тейк-профит)",
                parse_mode="Markdown"
            )
            return
        try:
            pair = parts[0].upper()
            direction = parts[1].lower()
            entry = float(parts[2].replace(",", "."))
            sl = float(parts[3].replace(",", ".")) if len(parts) > 3 else None
            tp = float(parts[4].replace(",", ".")) if len(parts) > 4 else None
            trade = {
                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "pair": pair,
                "direction": direction,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "result": None,
                "pnl": None,
            }
            user_journal.setdefault(uid, []).append(trade)
            ctx.user_data.pop("state", None)
            sl_str = f"\nСтоп-лосс: `{sl}`" if sl else ""
            tp_str = f"\nТейк-профит: `{tp}`" if tp else ""
            await update.message.reply_text(
                f"✅ Сделка добавлена!\n\n"
                f"Пара: `{pair}`\nНаправление: {direction}\nВход: `{entry}`{sl_str}{tp_str}\n\n"
                f"Когда закроешь сделку — добавь результат через журнал.",
                parse_mode="Markdown", reply_markup=journal_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Пример: `EURUSD buy 1.1000 1.0950 1.1100`", parse_mode="Markdown")

    # Закрытие сделки
    elif state == "journal_close":
        idx = ctx.user_data.get("close_idx")
        try:
            exit_price = float(text.replace(",", "."))
            trade = user_journal[uid][idx]
            trade["exit"] = exit_price
            trade["result"] = "win" if (
                (trade["direction"] == "buy" and exit_price > trade["entry"]) or
                (trade["direction"] == "sell" and exit_price < trade["entry"])
            ) else "loss"
            trade["pnl"] = round(exit_price - trade["entry"], 5) if trade["direction"] == "buy" else round(trade["entry"] - exit_price, 5)
            ctx.user_data.pop("state", None)
            emoji = "✅" if trade["result"] == "win" else "❌"
            await update.message.reply_text(
                f"{emoji} Сделка закрыта!\nРезультат: *{trade['result'].upper()}*\nP&L: `{trade['pnl']}`",
                parse_mode="Markdown", reply_markup=journal_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи цену закрытия, например: 1.1050")

    # Калькулятор риска
    elif state == "risk_input":
        parts = text.strip().split()
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", 1000)
        risk_pct = settings.get("risk_pct", 1)
        try:
            if len(parts) == 1:
                sl_pips = float(parts[0].replace(",", "."))
                risk_usd = deposit * risk_pct / 100
                lot = round(risk_usd / (sl_pips * 10), 2)
                await update.message.reply_text(
                    f"🧮 *Расчёт позиции:*\n\n"
                    f"Депозит: `${deposit}`\nРиск: `{risk_pct}%` = `${risk_usd}`\n"
                    f"Стоп-лосс: `{sl_pips} пунктов`\n\n"
                    f"💡 Размер лота: *{lot}*",
                    parse_mode="Markdown", reply_markup=risk_keyboard()
                )
            else:
                await update.message.reply_text("❌ Введи только количество пунктов стоп-лосса, например: `30`", parse_mode="Markdown")
            ctx.user_data.pop("state", None)
        except ValueError:
            await update.message.reply_text("❌ Введи число, например: 30")

    # Установка депозита
    elif state == "risk_deposit":
        parts = text.strip().split()
        try:
            deposit = float(parts[0].replace(",", "."))
            risk_pct = float(parts[1]) if len(parts) > 1 else 1.0
            user_settings.setdefault(uid, {})
            user_settings[uid]["deposit"] = deposit
            user_settings[uid]["risk_pct"] = risk_pct
            ctx.user_data.pop("state", None)
            await update.message.reply_text(
                f"✅ Настройки сохранены!\nДепозит: `${deposit}`\nРиск на сделку: `{risk_pct}%`",
                parse_mode="Markdown", reply_markup=risk_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи: `1000 1` (депозит и % риска)", parse_mode="Markdown")

    # Дневник психологии
    elif state == "diary_add":
        entry = {
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "text": text
        }
        user_diary.setdefault(uid, []).append(entry)
        ctx.user_data.pop("state", None)
        await update.message.reply_text(
            "✅ Запись добавлена в дневник!",
            reply_markup=diary_keyboard()
        )

    else:
        await update.message.reply_text("Используй /menu для навигации.", reply_markup=main_keyboard())

# ─── Callback ─────────────────────────────────────────────────────────────────

async def on_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    # Главное меню
    if data == "back_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_keyboard())

    elif data == "menu_pairs":
        await query.edit_message_text("📊 Выбери валютные пары:", reply_markup=pairs_keyboard(uid))

    elif data == "back_pairs":
        await query.edit_message_text("📊 Выбери валютные пары:", reply_markup=pairs_keyboard(uid))

    # ── Котировки ──
    elif data.startswith("toggle_"):
        pair = data[7:]
        subs = user_subscriptions.setdefault(uid, set())
        if pair in subs:
            base, quote = PAIRS[pair]
            rate = get_rate(base, quote)
            alerts = user_alerts.get(uid, {}).get(pair, {})
            above = alerts.get("above", "—")
            below = alerts.get("below", "—")
            await query.edit_message_text(
                f"🔔 *{pair}*\nТекущий курс: `{rate}`\n\nАлерт выше: `{above}`\nАлерт ниже: `{below}`",
                parse_mode="Markdown", reply_markup=alert_keyboard(pair)
            )
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
        ctx.user_data["state"] = "awaiting_price"
        ctx.user_data["awaiting_price"] = {"pair": pair, "direction": direction}
        emoji = "📈" if direction == "above" else "📉"
        await query.edit_message_text(
            f"{emoji} Введи цену для алерта по *{pair}*\n_(например: 1.0850)_",
            parse_mode="Markdown"
        )

    elif data.startswith("unsub_"):
        pair = data[6:]
        user_subscriptions.get(uid, set()).discard(pair)
        user_alerts.get(uid, {}).pop(pair, None)
        await query.edit_message_text(f"❌ Отписался от {pair}", reply_markup=pairs_keyboard(uid))

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

    # ── Новости ──
    elif data == "menu_news":
        await query.edit_message_text("⏳ Загружаю новости...")
        news = get_news()
        if not news:
            await query.edit_message_text("Новости недоступны. Попробуй позже.", reply_markup=main_keyboard())
            return
        lines = ["📰 *Последние новости Форекс:*\n"]
        for item in news:
            title = item.get("title", "")[:80]
            lines.append(f"• {title}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]]))

    # ── Журнал ──
    elif data == "menu_journal":
        await query.edit_message_text("📒 *Журнал сделок*\n\nЗдесь ты записываешь свои сделки и отслеживаешь статистику.", parse_mode="Markdown", reply_markup=journal_keyboard())

    elif data == "journal_add":
        ctx.user_data["state"] = "journal_add"
        await query.edit_message_text(
            "➕ Введи сделку в формате:\n`EURUSD buy 1.1000 1.0950 1.1100`\n\n"
            "пара → направление (buy/sell) → вход → стоп-лосс → тейк-профит\n"
            "_(стоп и тейк необязательны)_",
            parse_mode="Markdown"
        )

    elif data == "journal_list":
        trades = user_journal.get(uid, [])
        if not trades:
            await query.edit_message_text("Журнал пуст. Добавь первую сделку!", reply_markup=journal_keyboard())
            return
        lines = ["📋 *Последние сделки:*\n"]
        for i, t in enumerate(trades[-10:]):
            result = t.get("result", "открыта")
            pnl = f" | P&L: {t['pnl']}" if t.get("pnl") else ""
            emoji = "✅" if result == "win" else "❌" if result == "loss" else "🔄"
            lines.append(f"{emoji} {t['date']} | {t['pair']} {t['direction']} @ {t['entry']}{pnl}")
        keyboard = []
        trades_count = len(trades)
        for i in range(max(0, trades_count-5), trades_count):
            if not trades[i].get("result"):
                keyboard.append([InlineKeyboardButton(f"Закрыть #{i+1} {trades[i]['pair']}", callback_data=f"close_trade_{i}")])
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="menu_journal")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("close_trade_"):
        idx = int(data[12:])
        ctx.user_data["state"] = "journal_close"
        ctx.user_data["close_idx"] = idx
        trade = user_journal[uid][idx]
        await query.edit_message_text(
            f"Закрытие сделки {trade['pair']} {trade['direction']} @ {trade['entry']}\n\nВведи цену закрытия:",
        )

    elif data == "journal_stats":
        trades = user_journal.get(uid, [])
        closed = [t for t in trades if t.get("result")]
        if not closed:
            await query.edit_message_text("Нет закрытых сделок для статистики.", reply_markup=journal_keyboard())
            return
        wins = sum(1 for t in closed if t["result"] == "win")
        losses = len(closed) - wins
        winrate = round(wins / len(closed) * 100, 1)
        total_pnl = round(sum(t.get("pnl", 0) for t in closed), 5)
        await query.edit_message_text(
            f"📊 *Статистика*\n\n"
            f"Всего сделок: `{len(closed)}`\n"
            f"Прибыльных: `{wins}` ✅\n"
            f"Убыточных: `{losses}` ❌\n"
            f"Винрейт: `{winrate}%`\n"
            f"Общий P&L: `{total_pnl}`",
            parse_mode="Markdown", reply_markup=journal_keyboard()
        )

    # ── Калькулятор риска ──
    elif data == "menu_risk":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        await query.edit_message_text(
            f"🧮 *Калькулятор риска*\n\nДепозит: `${deposit}`\nРиск на сделку: `{risk_pct}%`",
            parse_mode="Markdown", reply_markup=risk_keyboard()
        )

    elif data == "risk_calc":
        settings = user_settings.get(uid, {})
        if not settings.get("deposit"):
            await query.edit_message_text("Сначала установи депозит!", reply_markup=risk_keyboard())
            return
        ctx.user_data["state"] = "risk_input"
        await query.edit_message_text("Введи размер стоп-лосса в *пунктах* (например: `30`):", parse_mode="Markdown")

    elif data == "risk_deposit":
        ctx.user_data["state"] = "risk_deposit"
        await query.edit_message_text(
            "Введи депозит и % риска через пробел:\n`1000 1`\n_(депозит в USD и риск в %)_",
            parse_mode="Markdown"
        )

    # ── Дневник психологии ──
    elif data == "menu_diary":
        await query.edit_message_text("🧠 *Дневник психологии*\n\nЗаписывай свои мысли и эмоции после сделок.", parse_mode="Markdown", reply_markup=diary_keyboard())

    elif data == "diary_add":
        ctx.user_data["state"] = "diary_add"
        await query.edit_message_text(
            "✍️ Напиши свои мысли о сегодняшней торговле:\n\n"
            "_(следовал ли плану, какие эмоции были, что можно улучшить)_",
            parse_mode="Markdown"
        )

    elif data == "diary_list":
        entries = user_diary.get(uid, [])
        if not entries:
            await query.edit_message_text("Дневник пуст. Добавь первую запись!", reply_markup=diary_keyboard())
            return
        lines = ["📖 *Последние записи:*\n"]
        for e in entries[-5:]:
            lines.append(f"📅 {e['date']}\n{e['text'][:100]}...\n")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=diary_keyboard())

    # ── Настройки ──
    elif data == "menu_settings":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        await query.edit_message_text(
            f"⚙️ *Настройки*\n\nДепозит: `${deposit}`\nРиск на сделку: `{risk_pct}%`\n\n"
            f"Чтобы изменить — перейди в Калькулятор риска → Установить депозит",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
        )

# ─── Проверка цен ─────────────────────────────────────────────────────────────

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

# ─── Запуск ───────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(app))
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
