import asyncio
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters,
)

BOT_TOKEN = "8828482180:AAE_Sdrqk5O5USAWpsShd2jetGt099J-Jso"
ALPHA_API_KEY = "3Q5QBKUEZZ7JFTA7"
CHECK_INTERVAL = 60

PAIRS = {
    "EUR/USD": ("EUR", "USD"), "GBP/USD": ("GBP", "USD"),
    "USD/JPY": ("USD", "JPY"), "USD/CHF": ("USD", "CHF"),
    "AUD/USD": ("AUD", "USD"), "USD/CAD": ("USD", "CAD"),
    "NZD/USD": ("NZD", "USD"), "EUR/GBP": ("EUR", "GBP"),
    "BTC/USD": ("BTC", "USD"), "ETH/USD": ("ETH", "USD"),
}

SWAP_RATES = {
    "EUR/USD": {"buy": -6.5, "sell": 1.2},
    "GBP/USD": {"buy": -4.8, "sell": 0.8},
    "USD/JPY": {"buy": 2.1,  "sell": -8.3},
    "USD/CHF": {"buy": 1.5,  "sell": -6.1},
    "AUD/USD": {"buy": -3.2, "sell": -1.1},
    "USD/CAD": {"buy": 0.9,  "sell": -5.4},
    "NZD/USD": {"buy": -2.8, "sell": -0.9},
    "EUR/GBP": {"buy": -3.1, "sell": 0.4},
    "BTC/USD": {"buy": -50.0,"sell": -50.0},
    "ETH/USD": {"buy": -30.0,"sell": -30.0},
}

PIP_VALUE = {
    "EUR/USD": 10.0, "GBP/USD": 10.0, "USD/JPY": 9.1,
    "USD/CHF": 10.0, "AUD/USD": 10.0, "USD/CAD": 7.7,
    "NZD/USD": 10.0, "EUR/GBP": 12.8, "BTC/USD": 1.0, "ETH/USD": 1.0,
}

PAIR_KEYWORDS = {
    "EUR/USD": ["euro", "eur", "ecb", "евро"],
    "GBP/USD": ["pound", "gbp", "boe", "фунт"],
    "USD/JPY": ["yen", "jpy", "boj", "иена"],
    "USD/CHF": ["franc", "chf", "snb", "франк"],
    "AUD/USD": ["aussie", "aud", "rba"],
    "USD/CAD": ["cad", "loonie", "boc"],
    "NZD/USD": ["nzd", "rbnz"],
    "EUR/GBP": ["euro", "pound", "ecb", "boe"],
    "BTC/USD": ["bitcoin", "btc"],
    "ETH/USD": ["ethereum", "eth"],
}

FED_CALENDAR = [
    {"date": "2026-06-17", "time": "22:00", "event": "Заседание ФРС — решение по ставке"},
    {"date": "2026-07-29", "time": "22:00", "event": "Заседание ФРС — решение по ставке"},
    {"date": "2026-09-16", "time": "22:00", "event": "Заседание ФРС — решение по ставке"},
    {"date": "2026-11-04", "time": "22:00", "event": "Заседание ФРС — решение по ставке"},
    {"date": "2026-12-16", "time": "22:00", "event": "Заседание ФРС — решение по ставке"},
    {"date": "2026-06-05", "time": "15:30", "event": "NFP — Число рабочих мест вне с/х (США)"},
    {"date": "2026-07-02", "time": "15:30", "event": "NFP — Число рабочих мест вне с/х (США)"},
    {"date": "2026-08-07", "time": "15:30", "event": "NFP — Число рабочих мест вне с/х (США)"},
    {"date": "2026-06-10", "time": "15:30", "event": "CPI США — Индекс потребительских цен"},
    {"date": "2026-07-14", "time": "15:30", "event": "CPI США — Индекс потребительских цен"},
    {"date": "2026-08-12", "time": "15:30", "event": "CPI США — Индекс потребительских цен"},
]

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

user_alerts: dict = {}
user_subscriptions: dict = {}
user_journal: dict = {}
user_settings: dict = {}
user_diary: dict = {}
user_voice_notes: dict = {}
news_keywords: dict = {}
news_pair_subs: dict = {}
sent_news_ids: dict = {}


def get_rate(base, quote):
    try:
        url = (f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE"
               f"&from_currency={base}&to_currency={quote}&apikey={ALPHA_API_KEY}")
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
        url = (f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
               f"&topics=forex&apikey={ALPHA_API_KEY}")
        r = requests.get(url, timeout=10)
        data = r.json()
        items = data.get("feed", [])
        if keywords:
            items = [i for i in items if any(
                k.lower() in i.get("title", "").lower() for k in keywords)]
        return items[:5]
    except Exception as e:
        logger.error(f"Ошибка новостей: {e}")
    return []


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
        [InlineKeyboardButton("📅 Календарь ФРС/НФП", callback_data="menu_calendar"),
         InlineKeyboardButton("📡 Новости по парам", callback_data="menu_news_pairs")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="menu_settings")],
    ])


def pairs_keyboard(uid):
    subs = user_subscriptions.get(uid, set())
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
        [InlineKeyboardButton("📊 Статистика", callback_data="journal_stats"),
         InlineKeyboardButton("📋 Последние 10", callback_data="journal_list")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])


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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить ключевое слово", callback_data="monitor_add")],
        [InlineKeyboardButton("🗑 Очистить список", callback_data="monitor_clear")],
        [InlineKeyboardButton("📰 Проверить сейчас", callback_data="monitor_check")],
        [InlineKeyboardButton("← Меню", callback_data="back_main")],
    ])


def news_pairs_keyboard(uid):
    subs = news_pair_subs.get(uid, set())
    buttons = []
    row = []
    for pair in PAIRS:
        mark = "✅ " if pair in subs else ""
        row.append(InlineKeyboardButton(f"{mark}{pair}", callback_data=f"newssub_{pair}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("← Меню", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)


async def cmd_start(update, ctx):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\nЯ твой торговый помощник. Выбери раздел 👇",
        reply_markup=main_keyboard()
    )


async def cmd_menu(update, ctx):
    await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())


async def on_message(update, ctx):
    uid = update.effective_user.id
    state = ctx.user_data.get("state")

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
            f"🎙 Голосовая заметка сохранена! Длительность: {note['duration']} сек.",
            reply_markup=voice_keyboard()
        )
        return

    text = update.message.text or ""

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
            await update.message.reply_text("❌ Формат: `EURUSD buy 1.1000 1.0950 1.1100`", parse_mode="Markdown")
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
            trade["pnl"] = round(
                exit_price - trade["entry"] if trade["direction"] == "buy"
                else trade["entry"] - exit_price, 5
            )
            ctx.user_data.pop("state", None)
            emoji = "✅" if trade["result"] == "win" else "❌"
            await update.message.reply_text(
                f"{emoji} Сделка закрыта! Результат: *{trade['result'].upper()}* | P&L: `{trade['pnl']}`",
                parse_mode="Markdown", reply_markup=journal_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи цену закрытия, например: 1.1050")

    elif state == "risk_input":
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
            sl_pips = round(sl_distance * 100 if "JPY" in pair else sl_distance * 10000, 1)
            risk_usd = deposit * risk_pct / 100
            lot = round(risk_usd / (sl_pips * pip_val), 2)
            ctx.user_data.pop("state", None)
            ctx.user_data.pop("risk_pair", None)
            await update.message.reply_text(
                f"🧮 *Расчёт позиции — {pair}*\n\n"
                f"Депозит: `${deposit}` | Риск: `{risk_pct}%` = `${risk_usd}`\n"
                f"Вход: `{entry}` | Стоп: `{sl}`\n"
                f"Расстояние: `{sl_pips} пп`\n\n"
                f"💡 *Размер лота: {lot}*\n"
                f"🎯 Тейк RR 1:2 = `${round(risk_usd * 2, 2)}`",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Введи: `1.1000 1.0950` (вход и стоп)", parse_mode="Markdown")

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
                f"✅ Сохранено! Депозит: `${deposit}` | Риск: `{risk_pct}%`",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Введи: `1000 1`", parse_mode="Markdown")

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
                f"_Начисляется каждую ночь в 00:00_",
                parse_mode="Markdown", reply_markup=main_keyboard()
            )
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Введи: `1.0 3` (лот и дни)", parse_mode="Markdown")

    elif state == "diary_add":
        user_diary.setdefault(uid, []).append({
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "text": text
        })
        ctx.user_data.pop("state", None)
        await update.message.reply_text("✅ Запись добавлена!", reply_markup=diary_keyboard())

    elif state == "monitor_add":
        keywords = [k.strip() for k in text.split(",")]
        news_keywords.setdefault(uid, []).extend(keywords)
        ctx.user_data.pop("state", None)
        await update.message.reply_text(
            f"✅ Добавлены: {', '.join(keywords)}\nВсе слова: {', '.join(news_keywords[uid])}",
            reply_markup=monitor_keyboard(uid)
        )

    else:
        await update.message.reply_text("Используй /menu для навигации.", reply_markup=main_keyboard())


async def on_callback(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "back_main":
        await query.edit_message_text("Главное меню:", reply_markup=main_keyboard())

    elif data in ("menu_pairs", "back_pairs"):
        await query.edit_message_text("📊 Выбери валютные пары:", reply_markup=pairs_keyboard(uid))

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
                f"✅ Подписался на {pair}{rate_str}\n\nНажми ещё раз для алерта:",
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

    elif data == "menu_news":
        await query.edit_message_text("⏳ Загружаю новости...")
        news = get_news()
        if not news:
            await query.edit_message_text("Новости недоступны.", reply_markup=main_keyboard())
            return
        lines = ["📰 *Последние новости Форекс:*\n"]
        for item in news:
            lines.append(f"• {item.get('title', '')[:80]}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
        )

    elif data == "menu_journal":
        await query.edit_message_text("📒 *Журнал сделок*", parse_mode="Markdown", reply_markup=journal_keyboard())

    elif data == "journal_add":
        ctx.user_data["state"] = "journal_add"
        await query.edit_message_text(
            "➕ Формат: `EURUSD buy 1.1000 1.0950 1.1100`\n\npair buy/sell entry sl tp",
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
        await query.edit_message_text(
            f"Закрытие {trade['pair']} {trade['direction']} @ {trade['entry']}\n\nВведи цену закрытия:"
        )

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
            f"📊 *Статистика*\n\nСделок: `{len(closed)}`\n✅ Прибыльных: `{wins}`\n"
            f"❌ Убыточных: `{losses}`\nВинрейт: `{winrate}%`\nОбщий P&L: `{total_pnl}`",
            parse_mode="Markdown", reply_markup=journal_keyboard()
        )

    elif data == "menu_risk":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        buttons = [[InlineKeyboardButton("💰 Установить депозит/риск", callback_data="risk_deposit")]]
        row = []
        for pair in PAIRS:
            row.append(InlineKeyboardButton(pair, callback_data=f"risk_pair_{pair}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("← Меню", callback_data="back_main")])
        await query.edit_message_text(
            f"🧮 *Калькулятор лота*\n\nДепозит: `${deposit}` | Риск: `{risk_pct}%`\n\nВыбери пару:",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("risk_pair_"):
        pair = data[10:]
        if not user_settings.get(uid, {}).get("deposit"):
            await query.edit_message_text(
                "❌ Сначала установи депозит!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="menu_risk")]])
            )
            return
        ctx.user_data["state"] = "risk_input"
        ctx.user_data["risk_pair"] = pair
        await query.edit_message_text(
            f"🧮 *{pair}* — введи вход и стоп через пробел:\n\n`1.1000 1.0950`",
            parse_mode="Markdown"
        )

    elif data == "risk_deposit":
        ctx.user_data["state"] = "risk_deposit"
        await query.edit_message_text(
            "Введи депозит и % риска:\n`1000 1`\n_(депозит в USD и % риска)_",
            parse_mode="Markdown"
        )

    elif data == "menu_swap":
        buttons = []
        row = []
        for pair in PAIRS:
            row.append(InlineKeyboardButton(pair, callback_data=f"swap_pair_{pair}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("← Меню", callback_data="back_main")])
        await query.edit_message_text("💱 *Своп-калькулятор*\n\nВыбери пару:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("swap_pair_"):
        pair = data[10:]
        rates = SWAP_RATES.get(pair, {"buy": 0, "sell": 0})
        ctx.user_data["state"] = "swap_input"
        ctx.user_data["swap_pair"] = pair
        await query.edit_message_text(
            f"💱 *{pair}*\n\nBuy: `{rates['buy']}` пп/день\nSell: `{rates['sell']}` пп/день\n\n"
            f"Введи лот и кол-во дней: `1.0 3`",
            parse_mode="Markdown"
        )

    elif data == "menu_diary":
        await query.edit_message_text("🧠 *Дневник психологии*", parse_mode="Markdown", reply_markup=diary_keyboard())

    elif data == "diary_add":
        ctx.user_data["state"] = "diary_add"
        await query.edit_message_text("✍️ Напиши мысли о сегодняшней торговле:", parse_mode="Markdown")

    elif data == "diary_list":
        entries = user_diary.get(uid, [])
        if not entries:
            await query.edit_message_text("Дневник пуст.", reply_markup=diary_keyboard())
            return
        lines = ["📖 *Последние записи:*\n"]
        for e in entries[-5:]:
            lines.append(f"📅 _{e['date']}_\n{e['text'][:120]}\n")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=diary_keyboard())

    elif data == "menu_voice":
        count = len(user_voice_notes.get(uid, []))
        await query.edit_message_text(
            f"🎙 *Голосовые заметки*\n\nСохранено: `{count}`\n\nПросто отправь голосовое сообщение!",
            parse_mode="Markdown", reply_markup=voice_keyboard()
        )

    elif data == "voice_list":
        notes = user_voice_notes.get(uid, [])
        if not notes:
            await query.edit_message_text("Нет голосовых заметок.", reply_markup=voice_keyboard())
            return
        await query.edit_message_text(f"🎙 Отправляю последние {min(5, len(notes))} заметок:", reply_markup=voice_keyboard())
        for note in notes[-5:]:
            caption = f"📅 {note['date']}" + (f"\n{note['text']}" if note.get("text") else "")
            await update.effective_message.reply_voice(voice=note["file_id"], caption=caption)

    elif data == "menu_monitor":
        keywords = news_keywords.get(uid, [])
        kw_str = ", ".join(keywords) if keywords else "не заданы"
        await query.edit_message_text(
            f"🔍 *Мониторинг новостей*\n\nКлючевые слова: `{kw_str}`",
            parse_mode="Markdown", reply_markup=monitor_keyboard(uid)
        )

    elif data == "monitor_add":
        ctx.user_data["state"] = "monitor_add"
        await query.edit_message_text("Введи ключевые слова через запятую:\n`ФРС, инфляция, NFP`", parse_mode="Markdown")

    elif data == "monitor_clear":
        news_keywords[uid] = []
        await query.edit_message_text("🗑 Список очищен.", reply_markup=monitor_keyboard(uid))

    elif data == "monitor_check":
        keywords = news_keywords.get(uid, [])
        if not keywords:
            await query.edit_message_text("Сначала добавь ключевые слова!", reply_markup=monitor_keyboard(uid))
            return
        await query.edit_message_text("⏳ Ищу новости...")
        news = get_news(keywords)
        if not news:
            await query.edit_message_text(f"Новостей по [{', '.join(keywords)}] не найдено.", reply_markup=monitor_keyboard(uid))
            return
        lines = [f"🔍 *Новости по: {', '.join(keywords)}*\n"]
        for item in news:
            lines.append(f"• {item.get('title', '')[:80]}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=monitor_keyboard(uid))

    elif data == "menu_calendar":
        now = datetime.now()
        upcoming = []
        for ev in FED_CALENDAR:
            ev_dt = datetime.strptime(f"{ev['date']} {ev['time']}", "%Y-%m-%d %H:%M")
            diff = ev_dt - now
            if 0 < diff.total_seconds() < 86400 * 30:
                upcoming.append((ev_dt, ev, diff.days, diff.seconds // 3600))
        upcoming.sort(key=lambda x: x[0])
        if not upcoming:
            text = "📅 *Экономический календарь*\n\nБлижайших событий в следующие 30 дней нет."
        else:
            lines = ["📅 *Экономический календарь (30 дней):*\n"]
            for ev_dt, ev, days, hours in upcoming[:10]:
                if days == 0:
                    time_str = f"сегодня в {ev['time']}"
                elif days == 1:
                    time_str = f"завтра в {ev['time']}"
                else:
                    time_str = f"{ev['date']} в {ev['time']} (через {days} дн.)"
                lines.append(f"🗓 {time_str}\n   _{ev['event']}_\n")
            text = "\n".join(lines)
        remind_on = user_settings.get(uid, {}).get("calendar_remind", False)
        remind_btn = "✅ Напоминания вкл" if remind_on else "🔔 Включить напоминания"
        remind_cb = "calendar_remind_off" if remind_on else "calendar_remind_on"
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(remind_btn, callback_data=remind_cb)],
                [InlineKeyboardButton("← Меню", callback_data="back_main")]
            ])
        )

    elif data == "calendar_remind_on":
        user_settings.setdefault(uid, {})["calendar_remind"] = True
        await query.edit_message_text(
            "✅ Напоминания включены!\n\nПришлю за *24 часа* и за *1 час* до каждого события.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отключить", callback_data="calendar_remind_off")],
                [InlineKeyboardButton("← Меню", callback_data="back_main")]
            ])
        )

    elif data == "calendar_remind_off":
        user_settings.setdefault(uid, {})["calendar_remind"] = False
        await query.edit_message_text(
            "❌ Напоминания отключены.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
        )

    elif data == "menu_news_pairs":
        subs = news_pair_subs.get(uid, set())
        await query.edit_message_text(
            f"📡 *Новости по парам*\n\nПодписано: {len(subs)} пар\n\n"
            f"Выбери пары — бот присылает новости как только они выходят:",
            parse_mode="Markdown", reply_markup=news_pairs_keyboard(uid)
        )

    elif data.startswith("newssub_"):
        pair = data[8:]
        subs = news_pair_subs.setdefault(uid, set())
        if pair in subs:
            subs.discard(pair)
            status = f"❌ Отписался от новостей по {pair}"
        else:
            subs.add(pair)
            status = f"✅ Подписался на новости по {pair}"
        await query.edit_message_text(
            f"{status}\n\nВыбери пары:",
            reply_markup=news_pairs_keyboard(uid)
        )

    elif data == "menu_settings":
        settings = user_settings.get(uid, {})
        deposit = settings.get("deposit", "не задан")
        risk_pct = settings.get("risk_pct", 1)
        remind = "✅ вкл" if settings.get("calendar_remind") else "❌ выкл"
        await query.edit_message_text(
            f"⚙️ *Настройки*\n\nДепозит: `${deposit}`\nРиск: `{risk_pct}%`\nНапоминания: {remind}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="back_main")]])
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
                        await app.bot.send_message(
                            chat_id=uid, text=f"🔔 *Алерт {pair}!*\n{msg}", parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка алерта: {e}")


async def monitor_news(app):
    while True:
        await asyncio.sleep(1800)
        for uid, keywords in list(news_keywords.items()):
            if not keywords:
                continue
            news = get_news(keywords)
            if news:
                lines = [f"🔍 *Новости по: {', '.join(keywords)}*\n"]
                for item in news:
                    lines.append(f"• {item.get('title', '')[:80]}")
                try:
                    await app.bot.send_message(chat_id=uid, text="\n".join(lines), parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Ошибка мониторинга: {e}")


async def pair_news_monitor(app):
    while True:
        await asyncio.sleep(300)
        for uid, pairs in list(news_pair_subs.items()):
            if not pairs:
                continue
            seen = sent_news_ids.setdefault(uid, set())
            for pair in pairs:
                keywords = PAIR_KEYWORDS.get(pair, [])
                news = get_news(keywords)
                for item in news:
                    news_id = item.get("url", item.get("title", ""))[:100]
                    if news_id in seen:
                        continue
                    seen.add(news_id)
                    title = item.get("title", "")[:100]
                    source = item.get("source", "")
                    try:
                        await app.bot.send_message(
                            chat_id=uid,
                            text=f"📡 *Новость по {pair}*\n\n{title}\n\n_Источник: {source}_",
                            parse_mode="Markdown"
                        )
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Ошибка новости: {e}")


async def calendar_reminders(app):
    while True:
        await asyncio.sleep(3600)
        now = datetime.now()
        for uid, settings in list(user_settings.items()):
            if not settings.get("calendar_remind"):
                continue
            for ev in FED_CALENDAR:
                ev_dt = datetime.strptime(f"{ev['date']} {ev['time']}", "%Y-%m-%d %H:%M")
                diff = ev_dt - now
                total_hours = diff.total_seconds() / 3600
                msg = None
                if 23 < total_hours <= 24:
                    msg = (f"🔔 *Напоминание — завтра!*\n\n"
                           f"📅 {ev['date']} в {ev['time']}\n_{ev['event']}_\n\n"
                           f"Подготовься к волатильности!")
                elif 0.9 < total_hours <= 1:
                    msg = (f"⚠️ *Через 1 час!*\n\n"
                           f"📅 Сегодня в {ev['time']}\n_{ev['event']}_\n\n"
                           f"Будь готов — возможна сильная волатильность!")
                if msg:
                    try:
                        await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Ошибка напоминания: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler((filters.TEXT | filters.VOICE) & ~filters.COMMAND, on_message))
    loop = asyncio.get_event_loop()
    loop.create_task(check_prices(app))
    loop.create_task(monitor_news(app))
    loop.create_task(pair_news_monitor(app))
    loop.create_task(calendar_reminders(app))
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
