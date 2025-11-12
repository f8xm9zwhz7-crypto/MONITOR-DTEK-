import os
import json
import asyncio
import logging
from datetime import datetime
import re

import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dtek_bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0") or 0)
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL", "120"))
DTEK_SHUTDOWNS_URL = "https://www.dtek-krem.com.ua/ua/shutdowns"
QUEUE_KEY = "1.1"
STORE_FILE = "dtek_state.json"

def load_state():
    if not os.path.exists(STORE_FILE):
        return {"status": "unknown", "last_update": None, "subs": []}
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"status": "unknown", "last_update": None, "subs": []}

def save_state(s):
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

state = load_state()
if "subs" not in state:
    state["subs"] = []

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (
        "Привіт! Я бот для відключень (черга 1.1).

"
        "Команди:
"
        "/subscribe — підписатися
"
        "/unsubscribe — відписатися
"
        "/status — поточний статус
"
    )
    await context.bot.send_message(chat_id=chat_id, text=text)

async def subscribe(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in state["subs"]:
        state["subs"].append(chat_id)
        save_state(state)
        await context.bot.send_message(chat_id=chat_id, text="Підписка оформлена ✅")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Ви вже підписані ✅")

async def unsubscribe(update, context):
    chat_id = update.effective_chat.id
    if chat_id in state["subs"]:
        state["subs"].remove(chat_id)
        save_state(state)
        await context.bot.send_message(chat_id=chat_id, text="Ви відписані ✅")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Вас немає в списку підписників.")

async def status_cmd(update, context):
    s = state.get("status", "unknown")
    last = state.get("last_update")
    txt = f"Поточний статус: *{s}*
Останнє оновлення: {last}" if last else f"Поточний статус: *{s}*"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=txt, parse_mode="Markdown")

KEYWORDS_OFF = ["вимкн", "відключ", "немає світла", "без світла", "вимкнуто"]
KEYWORDS_ON = ["увімкн", "віднов", "включ", "світло є", "відновлено"]

def normalize_text(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()

def detect_status(text: str):
    t = normalize_text(text)
    for k in KEYWORDS_OFF:
        if k in t:
            return "off"
    for k in KEYWORDS_ON:
        if k in t:
            return "on"
    if "заплан" in t or "графік" in t:
        return "scheduled"
    return None

def fetch_and_detect():
    try:
        resp = requests.get(DTEK_SHUTDOWNS_URL, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        elems = soup.find_all(text=re.compile(rf"\b{re.escape(QUEUE_KEY)}\b", re.IGNORECASE))
        aggregated = []
        for e in elems[:6]:
            node = e.parent
            textparts = []
            for _ in range(4):
                if node is None:
                    break
                txt = node.get_text(" ", strip=True)
                if txt:
                    textparts.append(txt)
                node = node.parent
            if textparts:
                aggregated.append(" ".join(textparts))
        big = " ||| ".join(aggregated)
        detected = detect_status(big)
        ts = datetime.utcnow().isoformat() + "Z"
        return detected, big, ts
    except:
        return None, None, None

def build_message(status, context, ts):
    if status == "off":
        return f"🔴 *Відключення світла* (черга {QUEUE_KEY})\nЧас (UTC): {ts}\n\n{context}"
    if status == "on":
        return f"🟢 *Світло відновлено* (черга {QUEUE_KEY})\nЧас (UTC): {ts}\n\n{context}"
    if status == "scheduled":
        return f"ℹ️ *Заплановані роботи* (черга {QUEUE_KEY})\nЧас (UTC): {ts}\n\n{context}"
    return f"❓ Статус не визначений (черга {QUEUE_KEY})\nЧас (UTC): {ts}\n\n{context or ''}"

async def broadcast(bot: Bot, text: str):
    for chat in state.get("subs", []):
        try:
            await bot.send_message(chat_id=chat, text=text, parse_mode="Markdown")
        except:
            pass
    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text="Повідомлення розіслано підписникам ✅")
        except:
            pass

async def monitor_task(app):
    bot = app.bot
    while True:
        status, context, ts = fetch_and_detect()
        if status and status != state.get("status"):
            state["status"] = status
            state["last_update"] = ts
            save_state(state)
            msg = build_message(status, context or "", ts)
            await broadcast(bot, msg)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("status", status_cmd))
    async with app:
        app.create_task(monitor_task(app))
        await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())