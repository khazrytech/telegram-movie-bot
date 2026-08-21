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
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("EnterpriseBot")

# Fetch Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
HF_KEY = os.getenv("HF_TOKEN")
TMDB_KEY = os.getenv("TMDB_API_KEY")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render URL

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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action_type TEXT,
            prompt TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

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
        logger.info(f"New user registered: {user_id} ({first_name})")
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
        
    current_credits = result["credits"]
    if current_credits >= amount:
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
# 3. AI ENGINE & BOT INITIALIZATION
# ==========================================
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY.strip())
    ai_model = genai.GenerativeModel('gemini-1.5-flash')
    logger.info("Gemini 1.5 Flash initialized successfully.")
else:
    ai_model = None
    logger.warning("GEMINI_API_KEY is missing. AI Chat functions will be disabled.")

bot = Bot(token=BOT_TOKEN.strip())
dp = Dispatcher(storage=MemoryStorage())

RATE_LIMIT_STORE: Dict[int, float] = {}

# ==========================================
# 4. CLICKPESA INTEGRATION ENGINE
# ==========================================
class ClickPesaClient:
    def __init__(self, api_key: str, client_id: str, secret_key: str):
        self.api_key = api_key
        self.client_id = client_id
        self.secret_key = secret_key
        self.base_url = "https://api.clickpesa.com/v1"

    def get_auth_header(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Client-Id": self.client_id or "",
            "Content-Type": "application/json"
        }

    async def initiate_mobile_money_payment(self, phone: str, amount: float, reference: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"success": False, "message": "ClickPesa API key missing."}

        url = f"{self.base_url}/payments/initialize"
        payload = {
            "amount": amount,
            "currency": "TZS",
            "phone_number": phone,
            "reference": reference,
            "description": f"Kununua Credit za Bot - Ref: {reference}"
        }

        try:
            async with ClientSession() as session:
                async with session.post(url, json=payload, headers=self.get_auth_header(), timeout=30) as resp:
                    data = await resp.json()
                    if resp.status in [200, 201]:
                        return {"success": True, "data": data}
                    else:
                        logger.error(f"ClickPesa Error: {data}")
                        return {"success": False, "message": data.get("message", "Payment processing failed")}
        except Exception as e:
            logger.error(f"ClickPesa Network Exception: {e}")
            return {"success": False, "message": str(e)}

clickpesa_client = ClickPesaClient(CLICKPESA_API_KEY, CLICKPESA_CLIENT_ID, CLICKPESA_SECRET_KEY)

# ==========================================
# 5. EXTERNAL APIS (TMDB & HUGGINGFACE)
# ==========================================
async def search_movie_tmdb(query: str) -> Dict[str, Any]:
    if not TMDB_KEY:
        return {"success": False, "message": "TMDB API Key haijawekwa."}
        
    url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_KEY.strip()}&query={query}&language=sw-TZ"
    try:
        async with ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        return {"success": True, "movie": results[0]}
                    return {"success": False, "message": "Hakuna muvi iliyopatikana kwa jina hilo."}
                return {"success": False, "message": f"TMDB Server Error: Status {resp.status}"}
    except Exception as e:
        logger.error(f"TMDB Fetch Error: {e}")
        return {"success": False, "message": "Imeshindikana kuunganisha na server ya Muvi."}

async def generate_flux_image(prompt: str) -> Optional[bytes]:
    if not HF_KEY:
        return None
        
    models = [
        "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
        "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
    ]
    
    headers = {"Authorization": f"Bearer {HF_KEY.strip()}"}
    payload = {"inputs": prompt}
    
    async with ClientSession(timeout=ClientTimeout(total=90)) as session:
        for model_url in models:
            try:
                async with session.post(model_url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        logger.warning(f"Model {model_url} failed with status {resp.status}")
            except Exception as e:
                logger.error(f"Error querying image model {model_url}: {e}")
    return None

# ==========================================
# 6. TELEGRAM BOT HANDLERS
# ==========================================

def is_rate_limited(user_id: int, limit_seconds: int = 3) -> bool:
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
        f"👋 **Jambo {user.first_name}! Karibu kwenye Enterprise AI Bot.**\n\n"
        "🤖 **AI Chat & Coding:** Uliza swali au omba kodi ya programu moja kwa moja.\n"
        "🎨 **AI Image Creator:** Tumia `/generate maelezo` kutengeneza picha.\n"
        "🎬 **Movie Finder:** Tumia `/movie jina_la_muvi` kupata maelezo ya muvi.\n"
        "💳 **Kununua Credit:** Tumia `/buy` kuongeza salio la kutumia AI.\n"
        "👤 **Akaunti Yako:** Tumia `/profile` kuangalia salio lako.\n\n"
        "🎁 *Umepewa Credit 10 za bure za kuanzia!*"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Nunua Credit", callback_data="buy_credits")],
        [InlineKeyboardButton(text="👤 Profile Yangu", callback_data="view_profile")],
        [InlineKeyboardButton(text="ℹ️ Msaada", callback_data="help_info")]
    ])
    
    await message.reply(welcome_card, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)
    credits = check_user_credits(user_id)
    
    profile_text = (
        f"👤 **PROFILE YAKO**\n\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"👤 **Jina:** {message.from_user.first_name}\n"
        f"🪙 **Salio la Credit:** `{credits if credits < 900000 else 'UNLIMITED VIP'}`\n"
        f"📅 **Aina ya Akaunti:** {'VIP Member 🌟' if credits > 900000 else 'Free User 🆓'}\n\n"
        "Ili kuongeza credit, tumia amri ya `/buy`."
    )
    await message.reply(profile_text, parse_mode="Markdown")

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    buy_text = (
        "💳 **NUNUA CREDIT ZA AI (CLICKPESA)**\n\n"
        "Chagua kifurushi unachotaka kupitia menu hapa chini:\n\n"
        "1️⃣ **Basic:** Credit 50 = TZS 1,000/=\n"
        "2️⃣ **Pro:** Credit 150 = TZS 2,500/=\n"
        "3️⃣ **Unlimited VIP:** Siku 30 = TZS 10,000/="
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Basic (50 Credit) - 1,000 TZS", callback_data="pay_1000")],
        [InlineKeyboardButton(text="🔥 Pro (150 Credit) - 2,500 TZS", callback_data="pay_2500")],
        [InlineKeyboardButton(text="👑 VIP Unlimited - 10,000 TZS", callback_data="pay_10000")]
    ])
    
    await message.reply(buy_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment_callback(callback: types.CallbackQuery):
    await callback.answer()
    plan = callback.data.replace("pay_", "")
    
    amount_map = {"1000": (1000, 50), "2500": (2500, 150), "10000": (10000, 999999)}
    if plan not in amount_map:
        await callback.message.reply("❌ Kifurushi kisichojulikana.")
        return
        
    amount, credits = amount_map[plan]
    await callback.message.reply(
        f"📲 **Kipengele cha Malipo:**\n\nTafadhali tumia amri hii kufanya malipo:\n"
        f"`/lipa 07xxxxxxxx {amount}`\n\n"
        f"Badilisha `07xxxxxxxx` na namba yako ya M-Pesa/Tigo/Airtel.",
        parse_mode="Markdown"
    )

@dp.message(Command("lipa"))
async def cmd_lipa(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("⚠️ **Matumizi Sahihi:** `/lipa 0762604237 1000`", parse_mode="Markdown")
        return

    args = command.args.split()
    if len(args) < 2:
        await message.reply("⚠️ Tafadhali weka namba ya simu na kiasi!\n**Mfano:** `/lipa 0762604237 1000`", parse_mode="Markdown")
        return

    phone, amount_str = args[0], args[1]
    
    clean_phone = re.sub(r"[^0-9]", "", phone)
    if clean_phone.startswith("0"):
        clean_phone = "255" + clean_phone[1:]
        
    if not (clean_phone.startswith("255") and len(clean_phone) == 12):
        await message.reply("❌ Namba ya simu siyo sahihi. Weka mfano: `0762604237` au `255762604237`", parse_mode="Markdown")
        return

    try:
        amount = float(amount_str)
        if amount < 500:
            await message.reply("❌ Kiasi cha chini cha malipo ni TZS 500/=")
            return
    except ValueError:
        await message.reply("❌ Kiasi lazima kiwe namba.")
        return

    credits_to_add = int(amount / 20)
    reference = f"TX-{message.from_user.id}-{int(time.time())}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO transactions (transaction_id, user_id, amount, phone_number, credits_added, status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
        (reference, message.from_user.id, amount, clean_phone, credits_to_add)
    )
    conn.commit()
    conn.close()

    status_msg = await message.reply("⏳ Inatuma ombi la malipo kwenda ClickPesa/Simu yako...")

    response = await clickpesa_client.initiate_mobile_money_payment(clean_phone, amount, reference)
    
    if response["success"]:
        await status_msg.edit_text(
            f"✅ **Ombi la Malipo Limetumwa!**\n\n"
            f"📱 Angalia simu yako (`{clean_phone}`) na uweke **PIN** yako kuthitibisha malipo ya **TZS {amount:,.0f}**.\n\n"
            f"🧾 **Reference ID:** `{reference}`\n"
            f"🪙 **Credit Utakazopata:** `{credits_to_add}`\n\n"
            f"*Ukishalipa, credit zitaongezeka kiotomatiki!*",
            parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(f"❌ Imeshindikana kuomba malipo: {response['message']}")

@dp.message(Command("movie"))
async def cmd_movie(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("⚠️ Weka jina la muvi!\n**Mfano:** `/movie Avengers`", parse_mode="Markdown")
        return

    query = command.args.strip()
    status_msg = await message.reply(f"🔍 Inatafuta muvi ya **'{query}'**...", parse_mode="Markdown")

    res = await search_movie_tmdb(query)
    if not res["success"]:
        await status_msg.edit_text(f"❌ {res['message']}")
        return

    m = res["movie"]
    title = m.get("title", "N/A")
    overview = m.get("overview", "Hakuna maelezo.")
    rating = m.get("vote_average", "N/A")
    release_date = m.get("release_date", "N/A")
    poster_path = m.get("poster_path")

    caption = (
        f"🎬 **{title}** ({release_date[:4] if release_date else 'N/A'})\n\n"
        f"⭐ **Rating:** {rating}/10\n"
        f"📅 **Tarehe ya Kutoka:** {release_date}\n\n"
        f"📝 **Maelezo:**\n{overview[:800]}..."
    )

    if poster_path:
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        await message.reply_photo(photo=poster_url, caption=caption, parse_mode="Markdown")
        await status_msg.delete()
    else:
        await status_msg.edit_text(caption, parse_mode="Markdown")

@dp.message(Command("generate"))
async def cmd_generate(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if is_rate_limited(user_id, limit_seconds=10):
        await message.reply("⏱️ Tafadhali subiri sekunde chache kabla ya kutengeneza picha nyingine.")
        return

    if not command.args:
        await message.reply("⚠️ Weka maelezo ya picha!\n**Mfano:** `/generate A lion wearing a golden crown in Serengeti`", parse_mode="Markdown")
        return

    if not deduct_user_credit(user_id, amount=2):
        await message.reply("❌ Huna Credit za kutosha! Kutengeneza picha inahitaji **Credit 2**. Tumia `/buy` kupata zingine.")
        return

    prompt = command.args.strip()
    status_msg = await message.reply("🎨 **AI inachora picha yako...** Subiri takriban sekunde 15-30.")

    img_bytes = await generate_flux_image(prompt)
    if img_bytes:
        photo = BufferedInputFile(img_bytes, filename="generated_image.png")
        await message.reply_photo(photo=photo, caption=f"🎨 **Prompt:** {prompt}\n⚡ *Credits Remaining: {check_user_credits(user_id)}*", parse_mode="Markdown")
        await status_msg.delete()
    else:
        add_user_credits(user_id, 2)
        await status_msg.edit_text("❌ Imeshindikana kutengeneza picha. Server zipo busy, jaribu tena baadae (Credit zako zimerudishwa).")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total_users FROM users")
    total_users = cursor.fetchone()["total_users"]
    cursor.execute("SELECT COUNT(*) as total_tx FROM transactions WHERE status='SUCCESS'")
    total_tx = cursor.fetchone()["total_tx"]
    conn.close()

    admin_panel = (
        f"⚙️ **ADMIN CONTROL PANEL**\n\n"
        f"👥 **Jumla ya Watumiaji:** `{total_users}`\n"
        f"💳 **Miamala Iliofanikiwa:** `{total_tx}`\n\n"
        "**Amri za Admin:**\n"
        "🔹 `/addcredit user_id amount` - Ongeza credit kwa mtumiaji\n"
        "🔹 `/broadcast ujumbe` - Tuma ujumbe kwa watumiaji wote"
    )
    await message.reply(admin_panel, parse_mode="Markdown")

@dp.message(Command("addcredit"))
async def cmd_add_credit(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.reply("Usage: `/addcredit 123456789 50`", parse_mode="Markdown")
        return
    try:
        target_id, amount = command.args.split()
        add_user_credits(int(target_id), int(amount))
        await message.reply(f"✅ Credit {amount} zimeongezwa kwa user `{target_id}`.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.reply("Usage: `/broadcast Hii ni taarifa mpya`")
        return
        
    text = command.args
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    count = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 **TANGAZO:**\n\n{text}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
            
    await message.reply(f"✅ Tangazo limetumwa kwa watumiaji {count}.")

@dp.message(F.text & ~F.text.startswith('/'))
async def ai_chat_handler(message: types.Message):
    user_id = message.from_user.id
    register_user(user_id, message.from_user.username, message.from_user.first_name)

    if is_rate_limited(user_id, limit_seconds=2):
        return

    if not ai_model:
        await message.reply("❌ Mfumo wa AI haujakamilika: `GEMINI_API_KEY` haijowekwa.")
        return

    if not deduct_user_credit(user_id, amount=1):
        await message.reply("❌ Credit zako zimeisha! Tumia `/buy` au `/profile` kuongeza salio la kutumia AI.")
        return

    thinking_msg = await message.reply("🤔 *AI inafikiria na kuandika jibu...*", parse_mode="Markdown")

    try:
        system_prompt = (
            "Wewe ni AI assistant mwenye akili sana na mtaalamu wa software engineering na uandishi wa kodi. "
            "Unajibu kwa kiswahili fasaha na kutoa kodi safi zenye maelezo kamili. "
            f"Swali la mtumiaji: {message.text}"
        )
        
        response = await asyncio.to_thread(ai_model.generate_content, system_prompt)
        reply_text = response.text if response.text else "⚠️ AI haijatoa jibu."

        if len(reply_text) > 4000:
            await thinking_msg.delete()
            chunks = [reply_text[i:i+4000] for i in range(0, len(reply_text), 4000)]
            for chunk in chunks:
                await message.reply(chunk)
        else:
            await thinking_msg.edit_text(reply_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Gemini Execution Error: {e}")
        add_user_credits(user_id, 1)
        await thinking_msg.edit_text("❌ Kutokana na tatizo la mtandao, jibu halijapatikana. Credit yako imerudishwa.")

# ==========================================
# 7. FLASK WEB SERVER & WEBHOOK INTEGRATION
# ==========================================
app = Flask(__name__)

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "system": "Enterprise Telegram AI Bot (Webhook Mode)",
        "timestamp": datetime.now().isoformat()
    }), 200

@app.route('/health')
def health_check():
    return "OK", 200

@app.route(WEBHOOK_PATH, methods=['POST'])
def telegram_webhook():
    """Inapokea maombi kutoka Telegram."""
    try:
        update = Update.model_validate(request.get_json(force=True), context={"bot": bot})
        asyncio.run(dp.feed_update(bot, update))
        return "OK", 200
    except Exception as e:
        logger.error(f"Error handling update: {e}")
        return "Error", 500

@app.route('/clickpesa-webhook', methods=['POST'])
def clickpesa_webhook():
    data = request.json or {}
    logger.info(f"Webhook Received: {json.dumps(data)}")
    
    status = data.get("status")
    reference = data.get("reference")
    
    if status == "SUCCESS" and reference:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, credits_added, status FROM transactions WHERE transaction_id = ?", (reference,))
        tx = cursor.fetchone()
        
        if tx and tx["status"] != "SUCCESS":
            user_id = tx["user_id"]
            credits_to_add = tx["credits_added"]
            
            cursor.execute("UPDATE transactions SET status = 'SUCCESS' WHERE transaction_id = ?", (reference,))
            cursor.execute("UPDATE users SET credits = credits + ? WHERE user_id = ?", (credits_to_add, user_id))
            conn.commit()
            
            asyncio.run(
                bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 **Malipo Yamefanikiwa!**\n\nCredit **+{credits_to_add}** zimeongezwa kwenye akaunti yako. Tumia `/profile` kuangalia salio lako.",
                    parse_mode="Markdown"
                )
            )
            logger.info(f"Payment reference {reference} successfully processed.")
        conn.close()

    return jsonify({"status": "acknowledged"}), 200

# Set Webhook automatically on startup
async def set_webhook():
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL.rstrip('/')}{WEBHOOK_PATH}"
        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook successfully set to {webhook_url}")
    else:
        logger.warning("RENDER_EXTERNAL_URL environment variable is missing!")

if __name__ == '__main__':
    # Initialize Webhook before starting Flask
    asyncio.run(set_webhook())
    
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

