import os
import re
import sys
import time
import math
import json
import sqlite3
import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

import requests
from aiohttp import ClientSession, ClientTimeout
from flask import Flask, request, jsonify

import google.generativeai as genai
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage

# ==========================================
# 1. LOGGING & CONFIGURATION MANAGEMENT
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("EnterpriseBot")

# Fetch Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
HF_KEY = os.getenv("HF_TOKEN")
TMDB_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

# ClickPesa Credentials
CLICKPESA_API_KEY = os.getenv("CLICKPESA_API_KEY")
CLICKPESA_CLIENT_ID = os.getenv("CLICKPESA_CLIENT_ID")
CLICKPESA_SECRET_KEY = os.getenv("CLICKPESA_SECRET_KEY")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

if not BOT_TOKEN:
    logger.critical("CRITICAL: BOT_TOKEN Environment variable is missing!")
    sys.exit(1)

# ==========================================
# 2. DATABASE ARCHITECTURE (SQLite)
# ==========================================
DB_FILE = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            credits INTEGER DEFAULT 10,
            is_vip INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            phone_number TEXT,
            status TEXT DEFAULT 'PENDING',
            credits_added INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def register_user(user_id: int, username: Optional[str], first_name: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, credits) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, 10)
        )
    else:
        cursor.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP, username = ?, first_name = ? WHERE user_id = ?",
            (username, first_name, user_id)
        )
    conn.commit()
    conn.close()

def check_user_credits(user_id: int) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT credits, is_vip FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        if result["is_vip"] == 1:
            return 999999
        return result["credits"]
    return 0

def deduct_user_credit(user_id: int, amount: int = 1) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT credits, is_vip FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False
    if result["is_vip"] == 1:
        conn.close()
        return True
    if result["credits"] >= amount:
        cursor.execute("UPDATE users SET credits = credits - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def add_user_credits(user_id: int, credits_to_add: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (credits_to_add, user_id))
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 3. AI ENGINE INITIALIZATION
# ==========================================
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY.strip())
    # Tumia model madhubuti ya gemini-1.5-flash
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
    logger.info("Gemini AI initialized successfully.")
else:
    ai_model = None

bot = Bot(token=BOT_TOKEN.strip())
dp = Dispatcher(storage=MemoryStorage())
RATE_LIMIT_STORE: Dict[int, float] = {}

# ==========================================
# 4. TELEGRAM BOT HANDLERS
# ==========================================

def is_rate_limited(user_id: int, limit_seconds: int = 2) -> bool:
    now = time.time()
    last_time = RATE_LIMIT_STORE.get(user_id, 0)
    if now - last_time < limit_seconds:
        return True
    RATE_LIMIT_STORE[user_id] = now
    return False

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    register_user(user.id, user.username, user.first_name)
    welcome_card = (
        f"👋 **Jambo {user.first_name}! Karibu kwenye Bot.**\n\n"
        "🤖 **AI Chat:** Niandikie chochote nami nitakujibu.\n"
        "🎨 **AI Image:** Tumia `/generate maelezo` kutengeneza picha.\n"
        "🎬 **Movie Finder:** Tumia `/movie jina` kupata taarifa za muvi.\n"
        "💳 **Credit:** Tumia `/profile` kuangalia salio lako au `/buy` kuongeza."
    )
    await message.reply(welcome_card, parse_mode="Markdown")

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    credits = check_user_credits(user_id)
    await message.reply(f"👤 **PROFILE YAKO**\n\n🪙 Salio la Credit: `{credits}`", parse_mode="Markdown")

# Main AI Chat Handler (Gemini)
@dp.message(F.text & ~F.text.startswith('/'))
async def ai_chat_handler(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)

    if is_rate_limited(user_id):
        return

    if not ai_model:
        await message.reply("❌ API Key ya Gemini haijawekwa kwenye Render Environment Variables.")
        return

    if not deduct_user_credit(user_id, amount=1):
        await message.reply("❌ Credit zako zimeisha! Tumia `/profile` kuangalia salio au Nunua credit mpya.")
        return

    thinking_msg = await message.reply("🤔 *Inafikiria...*", parse_mode="Markdown")

    try:
        # Tuma Ombi kwa Gemini kwa njia ya kuzuia Timeout
        prompt = f"Unajibu kwa kiswahili fasaha na kifupi au kwa kina kama umeombwa kodi. Swali: {message.text}"
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: ai_model.generate_content(prompt))
        
        reply_text = response.text if response and response.text else "⚠️ AI haijatoa jibu."

        if len(reply_text) > 4000:
            await thinking_msg.delete()
            chunks = [reply_text[i:i+4000] for i in range(0, len(reply_text), 4000)]
            for chunk in chunks:
                await message.reply(chunk)
        else:
            await thinking_msg.edit_text(reply_text)

    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        add_user_credits(user_id, 1) # Rudisha credit
        await thinking_msg.edit_text(f"❌ Imeshindikana kupata jibu kutoka Gemini AI.\n\n*Sababu:* `{str(e)[:100]}`\n*(Credit imerudishwa)*", parse_mode="Markdown")

# ==========================================
# 5. FLASK SERVER & WEBHOOK SETUP
# ==========================================
app = Flask(__name__)
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

@app.route('/')
def home():
    return "Bot status: Running OK", 200

@app.route(WEBHOOK_PATH, methods=['POST'])
def telegram_webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.model_validate(json_data, context={"bot": bot})
        asyncio.run(dp.feed_update(bot, update))
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook Feed Error: {e}")
        return "Error", 500

async def setup_bot_webhook():
    if RENDER_EXTERNAL_URL:
        full_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(url=full_url, drop_pending_updates=True)
        logger.info(f"Webhook successfully registered: {full_url}")
    else:
        logger.error("RENDER_EXTERNAL_URL environment variable is MISSING!")

if __name__ == '__main__':
    # Set Webhook kwanza
    asyncio.run(setup_bot_webhook())
    
    # Anzisha Web Server
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

