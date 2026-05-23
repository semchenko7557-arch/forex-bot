import asyncio
import logging
import requests
import json
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

# Своп-ставки (пункты в день, приблизительные рыночные значения)
SWAP_RATES = {
    "EUR/USD": {"buy": -6.5,  "sell": 1.2},
    "GBP/USD": {"buy": -4.8,  "sell": 0.8},
    "USD/JPY": {"buy": 2.1,   "sell": -8.3},
    "USD/CHF": {"buy": 1.5,   "sell": -6.1},
    "AUD/USD": {"buy": -3.2,  "sell": -1.1},
    "USD/CAD": {"buy": 0.9,   "sell": -5.4},
    "NZD/USD": {"buy": -2.8,  "sell": -0.9},
    "EUR/GBP": {"buy": -3.1,  "sell": 0.4},
    "BTC/USD": {"buy": -50.0, "sell": -50.0},
    "ETH/USD": {"buy": -30.0, "sell": -30.0},
}

# Размер пункта для расчёта лота (стоимость 1 пункта на 1 стандартный лот в USD)
PIP_VALUE = {
    "EUR/USD": 10.0,
    "GBP/USD": 10.0,
    "USD/JPY": 9.1,
    "USD/CHF": 10.0,
    "AUD/USD": 10.0,
    "USD/CAD": 7.7,
    "NZD/USD": 10.0,
    "EUR/GBP": 12.8,
    "BTC/USD": 1.0,
    "ETH/USD": 1.0,
}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

user_alerts: dict[int, dict[str, dict]] = {}
user_subscriptions: dict[int, set] = {}
user_journal: dict[int, list] = {}
user_settings: dict[int, dict] = {}
user_diary: dict[int, list] = {}
user_voice_notes: dict[int, list] = {}
news_keywords: dict[int, list] = {}

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

def get_news(keywords=None):
    try:
        url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=forex&apikey={ALPHA_API_KEY}"
        r = requests.get(url, timeout=10)
        data = r.json()
        items = data.get("feed", [])
        if keywords:
            items = [i for i in items if any(k.lower() in i.get("title","").lower() for k in keywords)]
        return items[:5]
    except Exception as e:
        logger.error(f"Ошибка новостей: {e}")
    return []

# ─── Клавиатуры ───────────────────────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Котировки и алерты", callback_data="menu_pairs"),
         InlineKeyboardButton("📰 Новости", callback_data="menu_news")],
        [InlineKeyboardButton("📒 Журнал сделок", callback_data="menu_journal"),
         InlineKeyboardButton("🧮 Калькулятор лота", callback_data="menu_risk")],
        [InlineKeyboardButton("💱 Своп-калькулятор", callback_data="menu_swap"),
         InlineKeyboardButton("🧠 Дневник психологии", callback_data="menu_diary")],
        [InlineKeyboardButton("🎙 Голосовые заметки", callback_data="menu_voice"),
         InlineKeyboardButton("🔍 Мониторинг новостей", callback_data="menu_monitor")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
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

def pairs_select_keyboard(prefix):
    buttons = []
    row = []
    for pair in PAIRS:
        row.append(InlineKeyboardButton(pair, callback_data=f"{prefix}{pair}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("← Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

def journal_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить сделку", callback_data="journal_add")],
        [InlineKeyboardButton("📊 Статистика", callback_data="journal_stats"),
         InlineKeyboardButton("📋 Последние 10", callback_data="journal_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

def swap_pairs_keyboard():
    return pairs_select_keyboard("swap_pair_")

def risk_pairs_keyboard():
    return pairs_select_keyboard("risk_pair_")

def diary_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Добавить запись", callback_data="diary_add")],
        [InlineKeyboardButton("📖 Последние записи", callback_data="diary_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

def voice_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Мои заметки", callback_data="voice_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

def monitor_keyboard(uid):
    keywords = news_keywords.get(uid, [])
    kw_str = ", ".join(keywords) if keywords else "не заданы"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить ключевое слово", callback_data="monitor_add")],
        [InlineKeyboardButton("🗑 Очистить список", callback_data="monitor_clear")],
        [InlineKeyboardButton("📰 Проверить сейчас", callback_data="monitor_check")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])

# ─── Команды ──────────────────────────────────────────────────────────────────

async def cmd_start(update, ctx):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\nЯ твой торговый помощник. Выбери раздел 👇",
        reply_markup=main_keyboard()
    )

async def cmd_menu(update, ctx):
    await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())

# ─── Обработчик сообщений ─────────────────────────────────────────────────────

async def on_message(update, ctx):
    uid = update.effective_user.id
    state = ctx.user_data.get("state")

    # Голосовое сообщение
    if update.message.voice:
        note = {
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "file_id": update.message.voice.file_id,
            "duration": update.message.voice.duration,
            "text": ctx.user_data.pop("voice_caption", ""),
        }
        user_voice_notes.setdefault(uid, []).append(note)
        ctx.user_data.pop("state", None)
        await update.message.reply_text(
            f"🎙 Голосовая заметка сохранена!\nДлительность: {note['duration']} сек.",
            reply_markup=voice_keyboard()
        )
        return

    text = update.message.text if update.message.text else ""

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

    elif state == "journal_add":
        parts = text.strip().split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Формат: `EURUSD buy 1.1000 1.0950 1.1100`",
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
                "pair": pair, "direction": direction,
                "entry": entry, "sl": sl, "tp": tp,
                "result": None, "pnl": None,
            }
            user_journal.setdefault(uid, []).append(trade)
            ctx.user_data.pop("state", None)
            sl_str = f"\nСтоп-лосс: `{sl}`" if sl else ""
            tp_str = f"\nТейк-профит: `{tp}`" if tp else ""
            await update.message.reply_text(
                f"✅ Сделка добавлена!\n`{pair}` {direction} @ `{entry}`{sl_str}{tp_str}",
                parse_mode="Markdown", reply_markup=journal_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Пример: `EURUSD buy 1.1000 1.0950 1.1100`", parse_mode="Markdown")

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
                f"{emoji} Сделка закрыта! Результат: *{trade['result'].upper()}* | P&L: `{trade['pnl']}`",
                parse_mode="Markdown", reply_markup=journal_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи цену закрытия, например: 1.1050")

    elif state == "risk_input":
        # Формат: вход стоп (например: 1.1000 1.0950)
        parts = text.strip().split()
        pair = ctx.user_data.get("risk_pair", "EUR/USD")
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", 1000)
        risk_pct = settings.get("risk_pct", 1)
        try:
            entry = float(parts[0].replace(",", "."))
            sl = float(parts[1].replace(",", "."))
            pip_val = PIP_VALUE.get(pair, 10.0)
            sl_distance = abs(entry - sl)
            # конвертируем дистанцию в пункты (для JPY пара — умножаем на 100, иначе на 10000)
            if "JPY" in pair:
                sl_pips = round(sl_distance * 100, 1)
            else:
                sl_pips = round(sl_distance * 10000, 1)
            risk_usd = deposit * risk_pct / 100
            lot = round(risk_usd / (sl_pips * pip_val), 2)
            rr_tp = round(risk_usd * 2, 2)
            ctx.user_data.pop("state", None)
            ctx.user_data.pop("risk_pair", None)
            await update.message.reply_text(
                f"🧮 *Расчёт позиции — {pair}*\n\n"
                f"Депозит: `${deposit}`\n"
                f"Риск: `{risk_pct}%` = `${risk_usd}`\n"
                f"Вход: `{entry}`\n"
                f"Стоп-лосс: `{sl}`\n"
                f"Расстояние до стопа: `{sl_pips} пунктов`\n\n"
                f"💡 *Размер лота: {lot}*\n"
                f"🎯 Тейк для RR 1:2 = `${rr_tp}`",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Введи: `1.1000 1.0950` (вход и стоп через пробел)", parse_mode="Markdown")

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
                f"✅ Сохранено!\nДепозит: `${deposit}` | Риск: `{risk_pct}%`",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи: `1000 1` (депозит и % риска)", parse_mode="Markdown")

    elif state == "swap_input":
        pair = ctx.user_data.get("swap_pair", "EUR/USD")
        parts = text.strip().split()
        try:
            lot = float(parts[0].replace(",", "."))
            days = int(parts[1]) if len(parts) > 1 else 1
            rates = SWAP_RATES.get(pair, {"buy": 0, "sell": 0})
            swap_buy = round(rates["buy"] * lot * days, 2)
            swap_sell = round(rates["sell"] * lot * days, 2)
            ctx.user_data.pop("state", None)
            ctx.user_data.pop("swap_pair", None)
            await update.message.reply_text(
                f"💱 *Своп — {pair}*\n\n"
                f"Лот: `{lot}` | Дней: `{days}`\n\n"
                f"📈 Buy своп: `{swap_buy}$`\n"
                f"📉 Sell своп: `{swap_sell}$`\n\n"
                f"_Своп начисляется каждую ночь в 00:00 по серверному времени._",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Введи: `1.0 3` (лот и количество дней)", parse_mode="Markdown")

    elif state == "diary_add":
        entry = {"date": datetime.now().strftime("%d.%m.%Y %H:%M"), "text": text}
        user_diary.setdefault(uid, []).append(entry)
        ctx.user_data.pop("state", None)
        await update.message.reply_text("✅ Запись добавлена!", reply_markup=diary_keyboard())

    elif state == "voice_caption":
        ctx.user_data["voice_caption"] = text
        ctx.user_data["state"] = "awaiting_voice"
        await update.message.reply_text("✅ Подпись сохранена! Теперь отправь голосовое сообщение 🎙")

    elif state == "monitor_add":
        keywords = [k.strip() for k in text.split(",")]
        news_keywords.setdefault(uid, []).extend(keywords)
        ctx.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Добавлены ключевые слова: {', '.join(keywords)}\n\n"
            f"Все слова: {', '.join(news_keywords[uid])}",
            reply_markup=monitor_keyboard(uid)
        )

    else:
        await update.message.reply_text("Используй /menu для навигации.", reply_markup=main_keyboard())

# ─── Callback ─────────────────────────────────────────────────────────────────

async def on_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

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
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
        )

    # ── Журнал ──
    elif data == "menu_journal":
        await query.edit_message_text("📒 *Журнал сделок*", parse_mode="Markdown", reply_markup=journal_keyboard())

    elif data == "journal_add":
        ctx.user_data["state"] = "journal_add"
        await query.edit_message_text(
            "➕ Введи сделку:\n`EURUSD buy 1.1000 1.0950 1.1100`\n\n"
            "пара → buy/sell → вход → стоп → тейк _(стоп и тейк необязательны)_",
            parse_mode="Markdown"
        )

    elif data == "journal_list":
        trades = user_journal.get(uid, [])
        if not trades:
            await query.edit_message_text("Журнал пуст.", reply_markup=journal_keyboard())
            return
        lines = ["📋 *Последние сделки:*\n"]
        for t in trades[-10:]:
            result = t.get("result", "открыта")
            pnl = f" P&L:{t['pnl']}" if t.get("pnl") else ""
            emoji = "✅" if result == "win" else "❌" if result == "loss" else "🔄"
            lines.append(f"{emoji} {t['date']} {t['pair']} {t['direction']} @{t['entry']}{pnl}")
        keyboard = []
        for i, t in enumerate(trades):
            if not t.get("result"):
                keyboard.append([InlineKeyboardButton(f"Закрыть #{i+1} {t['pair']}", callback_data=f"close_trade_{i}")])
        keyboard.append([InlineKeyboardButton("← Назад", callback_data="menu_journal")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("close_trade_"):
        idx = int(data[12:])
        ctx.user_data["state"] = "journal_close"
        ctx.user_data["close_idx"] = idx
        trade = user_journal[uid][idx]
        await query.edit_message_text(f"Закрытие {trade['pair']} {trade['direction']} @ {trade['entry']}\n\nВведи цену закрытия:")

    elif data == "journal_stats":
        trades = user_journal.get(uid, [])
        closed = [t for t in trades if t.get("result")]
        if not closed:
            await query.edit_message_text("Нет закрытых сделок.", reply_markup=journal_keyboard())
            return
        wins = sum(1 for t in closed if t["result"] == "win")
        losses = len(closed) - wins
        winrate = round(wins / len(closed) * 100, 1)
        total_pnl = round(sum(t.get("pnl", 0) for t in closed), 5)
        await query.edit_message_text(
            f"📊 *Статистика*\n\n"
            f"Сделок: `{len(closed)}`\n✅ Прибыльных: `{wins}`\n❌ Убыточных: `{losses}`\n"
            f"Винрейт: `{winrate}%`\nОбщий P&L: `{total_pnl}`",
            parse_mode="Markdown", reply_markup=journal_keyboard()
        )

    # ── Калькулятор лота ──
    elif data == "menu_risk":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        await query.edit_message_text(
            f"🧮 *Калькулятор лота*\n\nДепозит: `${deposit}` | Риск: `{risk_pct}%`\n\nВыбери пару для расчёта:",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("💰 Установить депозит/риск", callback_data="risk_deposit")]] +
                [[InlineKeyboardButton(p, callback_data=f"risk_pair_{p}")] for p in list(PAIRS.keys())[:5]] +
                [[InlineKeyboardButton(p, callback_data=f"risk_pair_{p}")] for p in list(PAIRS.keys())[5:]] +
                [[InlineKeyboardButton("← Меню", callback_data="back_main")]]
            )
        )

    elif data.startswith("risk_pair_"):
        pair = data[10:]
        if not user_settings.get(uid, {}).get("deposit"):
            await query.edit_message_text(
                "❌ Сначала установи депозит!\nНажми 'Установить депозит/риск'.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="menu_risk")]])
            )
            return
        ctx.user_data["state"] = "risk_input"
        ctx.user_data["risk_pair"] = pair
        await query.edit_message_text(
            f"🧮 *{pair}* — введи точку входа и стоп-лосс через пробел:\n\n"
            f"`1.1000 1.0950`\n\n_(вход и стоп-лосс)_",
            parse_mode="Markdown"
        )

    elif data == "risk_deposit":
        ctx.user_data["state"] = "risk_deposit"
        await query.edit_message_text(
            "Введи депозит и % риска через пробел:\n`1000 1`\n_(депозит в USD и риск в %)_",
            parse_mode="Markdown"
        )

    # ── Своп-калькулятор ──
    elif data == "menu_swap":
        await query.edit_message_text(
            "💱 *Своп-калькулятор*\n\nВыбери пару:",
            parse_mode="Markdown", reply_markup=swap_pairs_keyboard()
        )

    elif data.startswith("swap_pair_"):
        pair = data[10:]
        rates = SWAP_RATES.get(pair, {"buy": 0, "sell": 0})
        ctx.user_data["state"] = "swap_input"
        ctx.user_data["swap_pair"] = pair
        await query.edit_message_text(
            f"💱 *{pair}*\n\n"
            f"Ставки свопа:\n📈 Buy: `{rates['buy']}` пунктов/день\n📉 Sell: `{rates['sell']}` пунктов/день\n\n"
            f"Введи лот и количество дней через пробел:\n`1.0 3`",
            parse_mode="Markdown"
        )

    # ── Дневник ──
    elif data == "menu_diary":
        await query.edit_message_text("🧠 *Дневник психологии*", parse_mode="Markdown", reply_markup=diary_keyboard())

    elif data == "diary_add":
        ctx.user_data["state"] = "diary_add"
        await query.edit_message_text(
            "✍️ Напиши свои мысли о сегодняшней торговле:\n_(эмоции, ошибки, что улучшить)_",
            parse_mode="Markdown"
        )

    elif data == "diary_list":
        entries = user_diary.get(uid, [])
        if not entries:
            await query.edit_message_text("Дневник пуст.", reply_markup=diary_keyboard())
            return
        lines = ["📖 *Последние записи:*\n"]
        for e in entries[-5:]:
            lines.append(f"📅 _{e['date']}_\n{e['text'][:120]}\n")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=diary_keyboard())

    # ── Голосовые заметки ──
    elif data == "menu_voice":
        notes = user_voice_notes.get(uid, [])
        count = len(notes)
        await query.edit_message_text(
            f"🎙 *Голосовые заметки*\n\nСохранено заметок: `{count}`\n\n"
            f"Просто отправь голосовое сообщение — я его сохраню!\n"
            f"Можешь сначала написать подпись текстом, потом отправить голосовое.",
            parse_mode="Markdown", reply_markup=voice_keyboard()
        )

    elif data == "voice_list":
        notes = user_voice_notes.get(uid, [])
        if not notes:
            await query.edit_message_text("Нет голосовых заметок.", reply_markup=voice_keyboard())
            return
        await query.edit_message_text(
            f"🎙 *Твои голосовые заметки ({len(notes)}):*\n\nОтправь /menu и перейди в голосовые — бот пришлёт их по очереди.",
            parse_mode="Markdown", reply_markup=voice_keyboard()
        )
        for note in notes[-5:]:
            caption = f"📅 {note['date']}" + (f"\n{note['text']}" if note.get("text") else "")
            await update.effective_message.reply_voice(voice=note["file_id"], caption=caption)

    # ── Мониторинг новостей ──
    elif data == "menu_monitor":
        keywords = news_keywords.get(uid, [])
        kw_str = ", ".join(keywords) if keywords else "не заданы"
        await query.edit_message_text(
            f"🔍 *Мониторинг новостей*\n\nКлючевые слова: `{kw_str}`\n\n"
            f"Бот будет присылать новости содержащие твои ключевые слова каждые 30 минут.",
            parse_mode="Markdown", reply_markup=monitor_keyboard(uid)
        )

    elif data == "monitor_add":
        ctx.user_data["state"] = "monitor_add"
        await query.edit_message_text(
            "Введи ключевые слова через запятую:\n`ФРС, инфляция, NFP, EUR`",
            parse_mode="Markdown"
        )

    elif data == "monitor_clear":
        news_keywords[uid] = []
        await query.edit_message_text("🗑 Список ключевых слов очищен.", reply_markup=monitor_keyboard(uid))

    elif data == "monitor_check":
        keywords = news_keywords.get(uid, [])
        if not keywords:
            await query.edit_message_text("Сначала добавь ключевые слова!", reply_markup=monitor_keyboard(uid))
            return
        await query.edit_message_text("⏳ Ищу новости...")
        news = get_news(keywords)
        if not news:
            await query.edit_message_text(
                f"Новостей по словам [{', '.join(keywords)}] не найдено.",
                reply_markup=monitor_keyboard(uid)
            )
            return
        lines = [f"🔍 *Новости по: {', '.join(keywords)}*\n"]
        for item in news:
            lines.append(f"• {item.get('title','')[:80]}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=monitor_keyboard(uid))

    # ── Настройки ──
    elif data == "menu_settings":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        await query.edit_message_text(
            f"⚙️ *Настройки*\n\nДепозит: `${deposit}`\nРиск на сделку: `{risk_pct}%`\n\n"
            f"Изменить → Калькулятор лота → Установить депозит/риск",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
        )

# ─── Мониторинг новостей (фоновый) ───────────────────────────────────────────

async def monitor_news(app):
    while True:
        await asyncio.sleep(1800)  # каждые 30 минут
        for uid, keywords in list(news_keywords.items()):
            if not keywords:
                continue
            news = get_news(keywords)
            if news:
                lines = [f"🔍 *Новости по: {', '.join(keywords)}*\n"]
                for item in news:
                    lines.append(f"• {item.get('title','')[:80]}")
                try:
                    await app.bot.send_message(chat_id=uid, text="\n".join(lines), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Ошибка мониторинга: {e}")

# ─── Проверка алертов ─────────────────────────────────────────────────────────

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
    app.add_handler(MessageHandler((filters.TEXT | filters.VOICE) & ~filters.COMMAND, on_message))
    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(app))
    loop.create_task(monitor_news(app))
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
