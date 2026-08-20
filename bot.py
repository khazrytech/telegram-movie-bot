import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
)

# --- CONFIGURATION ---
ADMIN_ID = os.getenv("ADMIN_ID", "1846737920")
TOKEN = os.getenv("BOT_TOKEN", "8641125457:AAGem16-Y8ekNisn8ZRtzIfHcrW7tMJzyj0")
SONICPESA_API_KEY = os.getenv("SONICPESA_API_KEY", "")

# Memory Storage
PAYMENTS_DB = {}   # reference -> user_id
USER_IDS = set()   # Orodha ya watumiaji kwa ajili ya broadcast

# --- FLASK SERVER (WEBHOOK & HEALTH CHECK) ---
app = Flask(__name__)

@app.route('/sonicpesa-webhook', methods=['POST'])
def sonicpesa_webhook():
    data = request.json or {}
    print(f"📌 Webhook Received: {data}")

    reference = str(data.get("reference") or data.get("trans_id") or "")
    status = str(data.get("status", "")).upper()
    amount = data.get("amount", 1000)
    phone = data.get("phone") or data.get("accountnumber") or "N/A"

    if status in ["SUCCESS", "SUCCESSFUL", "COMPLETED", "200", "PAID"]:
        user_id = PAYMENTS_DB.get(reference, ADMIN_ID)
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        # 1. Ujumbe kwa Mtumiaji
        if str(user_id) != str(ADMIN_ID):
            user_msg = (
                f"🎉 **MALIPO YAMEPOKELEWA!**\n\n"
                f"💰 **Kiasi:** TZS {amount}\n"
                f"🆔 **Muamala:** `{reference}`\n\n"
                f"Asante kwa kulipia! Sasa unaweza kuendelea kutafuta na kudownload muvi bila kikomo."
            )
            requests.post(url, json={"chat_id": user_id, "text": user_msg, "parse_mode": "Markdown"})

        # 2. Ujumbe kwa Admin
        admin_msg = (
            f"✅ **MALIPO MPYA YAMEKAMILIKA!**\n\n"
            f"👤 **User ID:** `{user_id}`\n"
            f"📞 **Simu:** `{phone}`\n"
            f"💰 **Kiasi:** TZS {amount}\n"
            f"🆔 **Ref:** `{reference}`"
        )
        requests.post(url, json={"chat_id": ADMIN_ID, "text": admin_msg, "parse_mode": "Markdown"})

    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "Kadomovie Bot & Webhook Service is Running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

Thread(target=run_flask, daemon=True).start()

# --- SONICPESA PAYMENT REQUEST ---
def request_sonicpesa_payment(phone_number, amount):
    url = "https://sonicpesa.com/api/v1/checkout"
    headers = {
        "Authorization": f"Bearer {SONICPESA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "api_key": SONICPESA_API_KEY,
        "phone": phone_number,
        "amount": int(amount)
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"📌 SonicPesa Status Code: {response.status_code}")
        print(f"📌 SonicPesa Response: {response.text}")

        if "application/json" in response.headers.get("Content-Type", ""):
            return response.json()
        else:
            return {
                "success": False, 
                "error": f"API Error ({response.status_code}): Hakikisha SONICPESA_API_KEY iko sahihi kwenye Render."
            }
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- TELEGRAM BOT COMMANDS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_IDS.add(user_id)
    
    await update.message.reply_text(
        "👋 **Karibu kwenye Kadomovie Bot!**\n\n"
        "🎬 **Tafuta Muvi:** Andika tu jina la muvi (Mfano: `Mjukuu` au `Babu`).\n"
        "💳 **Lipia Huduma:** Andika `/lipa 07xxxxxxxx` ili kulipia TZS 1,000 kwa wiki.",
        parse_mode="Markdown"
    )

async def lipa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_IDS.add(user_id)
    args = context.args

    if not args:
        await update.message.reply_text(
            "💳 **Jinsi ya Kulipia Subscriptions:**\n"
            "Andika: `/lipa 0712345678`\n\n"
            "Gharama: **1,000 TZS** kwa wiki.",
            parse_mode="Markdown"
        )
        return

    # Inasafisha namba na kuondoa nafasi au alama zozote zisizo namba
    raw_phone = "".join(args)
    phone = re.sub(r'\D', '', raw_phone)

    if phone.startswith("255"):
        phone = "0" + phone[3:]

    if len(phone) != 10:
        await update.message.reply_text("❌ Namba sio sahihi. Hakikisha ina tarakimu 10 (Mfano: `/lipa 0747431855`).", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"🔄 Inatuma ombi la malipo kwenda `{phone}`...", parse_mode="Markdown")

    res = request_sonicpesa_payment(phone, 1000)

    if res.get("status") in [True, "success", "PENDING", 200]:
        reference = str(res.get("reference") or res.get("trans_id") or user_id)
        PAYMENTS_DB[reference] = str(user_id)
        await msg.edit_text("📱 **Popup imetumwa kwenye simu yako!**\nIngiza **PIN** yako kukamilisha muamala.")
    else:
        err_msg = res.get("message") or res.get("error") or "Imeshindikana kutuma ombi la malipo."
        await msg.edit_text(f"❌ **Hitilafu:** {err_msg}")

# --- ADMIN COMMANDS ---

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Huna ruhusa ya kutumia command hii.")
        return

    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("⚠️ Andika ujumbe! Mfano: `/broadcast Leo kuna muvi mpya zimeongezwa!`", parse_mode="Markdown")
        return

    success_count = 0
    await update.message.reply_text(f"📢 Inatuma ujumbe kwa watumiaji {len(USER_IDS)}...")

    for uid in list(USER_IDS):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 **TAARIFA:**\n\n{message_text}", parse_mode="Markdown")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception:
            continue

    await update.message.reply_text(f"✅ Ujumbe umetumwa kikamilifu kwa watumiaji **{success_count}**!")

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("❌ Huna ruhusa ya kutumia command hii.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("⚠️ Tumia hivi: `/send USER_ID Ujumbe wako`", parse_mode="Markdown")
        return

    target_id = context.args[0]
    custom_msg = " ".join(context.args[1:])

    try:
        await context.bot.send_message(chat_id=target_id, text=f"📩 **Ujumbe kutoka kwa Admin:**\n\n{custom_msg}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Ujumbe umetumwa kwa `{target_id}`!")
    except Exception as e:
        await update.message.reply_text(f"❌ Imeshindikana kutuma: {e}")

# --- MOVIE SEARCH HANDLER ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    USER_IDS.add(user.id)
    query = update.message.text.strip()
    
    # Mtaarifu Admin wakati mtumiaji anatafuta
    if str(user.id) != str(ADMIN_ID):
        try:
            admin_msg = f"🔔 **Mtumiaji:** {user.first_name} (`{user.id}`)\n🔍 **Ametafuta:** `{query}`"
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        except Exception:
            pass

    msg = await update.message.reply_text(f"🔍 Inatafuta muvi za '{query}'...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    results = []
    query_clean = query.lower().strip()

    for page in range(1, 4):
        search_url = f"https://www.absalomfamily.com/?s={query}" if page == 1 else f"https://www.absalomfamily.com/page/{page}/?s={query}"
        try:
            res = requests.get(search_url, headers=headers, timeout=12)
            if res.status_code != 200:
                break

            soup = BeautifulSoup(res.text, 'html.parser')
            
            for a_tag in soup.find_all('a'):
                title = a_tag.get_text().strip()
                href = a_tag.get('href', '')

                if query_clean in title.lower() and href.startswith('http') and 'drive.google.com' not in href:
                    if not any(r['url'] == href for r in results) and len(title) > 3:
                        results.append({'title': title, 'url': href})
                        
        except Exception:
            break

    if not results:
        await msg.edit_text(f"❌ Hakuna muvi iliyopatikana kwa '{query}'. Jaribu kutafuta kwa neno moja pekee.")
        return

    await msg.edit_text(f"✅ Nimepata muvi {len(results)}! Inazituma...")

    for item in results:
        try:
            p_res = requests.get(item['url'], headers=headers, timeout=12)
            p_soup = BeautifulSoup(p_res.text, 'html.parser')

            drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', p_res.text)
            drive_text = drive_links[0].rstrip('.,;') if drive_links else "⚠️ Link haijapatikana kwasasa"

            poster_url = None
            og_image = p_soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                poster_url = og_image['content']

            caption = f"🎬 **Muvi:** {item['title']}\n\n📁 **Download Link:**\n{drive_text}"

            if poster_url:
                await update.message.reply_photo(photo=poster_url, caption=caption, parse_mode="Markdown")
            else:
                await update.message.reply_text(caption, parse_mode="Markdown")

            await asyncio.sleep(1.2)
        except Exception:
            continue

# --- START BOT ---
if __name__ == '__main__':
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    app_bot.add_handler(CommandHandler(["start", "help"], start_command))
    app_bot.add_handler(CommandHandler("lipa", lipa_command))
    app_bot.add_handler(CommandHandler("broadcast", broadcast_command))
    app_bot.add_handler(CommandHandler("send", send_command))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app_bot.run_polling()
