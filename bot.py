import os
import re
import time
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

PAYMENTS_DB = {}   # reference -> user_id
USER_IDS = set()   # Orodha ya watumiaji kwa ajili ya broadcast

# --- FLASK SERVER (WEBHOOK & HEALTH CHECK) ---
app = Flask(__name__)

@app.route('/sonicpesa-webhook', methods=['POST'])
def sonicpesa_webhook():
    data = request.json or {}
    print(f"📌 Webhook Received: {data}")

    reference = str(data.get("reference") or data.get("trans_id") or data.get("order_id") or "")
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
def request_sonicpesa_payment(phone_number, amount, user_id):
    url = "https://api.sonicpesa.com/api/v1/payment/create_order"
    
    # Soma na usafishe API Key
    raw_key = os.getenv("SONICPESA_API_KEY", "").strip().strip('"').strip("'")
    
    if not raw_key:
        return {
            "status": "error",
            "message": "API Key haijapatikana! Hakikisha SONICPESA_API_KEY imewekwa kwenye Render."
        }

    # Format ya namba 255...
    clean_phone = re.sub(r'\D', '', str(phone_number))
    if clean_phone.startswith("0"):
        clean_phone = "255" + clean_phone[1:]
    elif not clean_phone.startswith("255"):
        clean_phone = "255" + clean_phone

    ref_id = f"KADO{user_id}{int(time.time())}"

    # Headers bila 'Bearer ' kuzuia Invalid Bearer Token Error
    headers = {
        "Authorization": raw_key,
        "X-API-KEY": raw_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload = {
        "api_key": raw_key,
        "phone": clean_phone,
        "amount": int(amount),
        "reference": ref_id,
        "description": "Malipo ya Kadomovie",
        "currency": "TZS"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        print(f"📌 SonicPesa Status Code: {response.status_code}")
        print(f"📌 SonicPesa Response Text: {response.text}")

        if response.status_code in [200, 201]:
            res_data = response.json()
            if isinstance(res_data, dict):
                res_data["custom_ref"] = ref_id
            return res_data
        else:
            return {
                "status": "error",
                "message": f"Hitilafu kutoka SonicPesa ({response.status_code}): {response.text}"
            }
    except Exception as e:
        return {"status": "error", "message": f"Network error: {str(e)}"}

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

    raw_phone = "".join(args)
    phone = re.sub(r'\D', '', raw_phone)

    if phone.startswith("0"):
        phone = "255" + phone[1:]
    elif not phone.startswith("255"):
        phone = "255" + phone

    if len(phone) != 12:
        await update.message.reply_text("❌ Namba sio sahihi. Hakikisha ina tarakimu sahihi (Mfano: `/lipa 0747431855`).", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(f"🔄 Inatuma ombi la malipo kwenda `0{phone[3:]}`...", parse_mode="Markdown")

    try:
        res = await asyncio.to_thread(request_sonicpesa_payment, phone, 1000, user_id)

        if res.get("status") in ["success", True, 200] or "order_id" in str(res):
            data_obj = res.get("data", {}) if isinstance(res.get("data"), dict) else {}
            reference = str(data_obj.get("reference") or res.get("custom_ref") or user_id)
            
            PAYMENTS_DB[reference] = str(user_id)
            await msg.edit_text("📱 **Popup imetumwa kwenye simu yako!**\nIngiza **PIN** yako kukamilisha muamala.")
        else:
            err_msg = res.get("message") or "Imeshindikana kutuma ombi la malipo."
            await msg.edit_text(f"❌ **Hitilafu:** {err_msg}")
    except Exception as e:
        await msg.edit_text(f"❌ **Kosa la Mfumo:** {str(e)}")

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

            raw_drive_links = re.findall(r'https://drive\.google\.com/file/d/[a-zA-Z0-9_-]+', p_res.text)
            if raw_drive_links:
                drive_text = f"{raw_drive_links[0]}/view?usp=drivesdk"
            else:
                drive_text = "⚠️ Link haijapatikana au imefutwa kwasasa"

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
