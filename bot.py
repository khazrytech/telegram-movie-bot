import os
import re
import asyncio
import requests
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

# --- FLASK SERVER KWA AJILI YA WEBHOOK NA HEALTH CHECK ---
app = Flask(__name__)

ADMIN_ID = "1846737920"
TOKEN = os.getenv("BOT_TOKEN", "8641125457:AAGem16-Y8ekNisn8ZRtzIfHcrW7tMJzyj0")
SONICPESA_API_KEY = os.getenv("SONICPESA_API_KEY", "")

# Memory ya kuhifadhi miamala
PAYMENTS_DB = {}

# Webhook Endpoint (SonicPesa itatuma majibu hapa baada ya malipo)
@app.route('/sonicpesa-webhook', methods=['POST'])
def sonicpesa_webhook():
    data = request.json or {}
    print(f"📌 SonicPesa Webhook Received: {data}")

    reference = data.get("reference") or data.get("trans_id")
    status = str(data.get("status", "")).upper()
    amount = data.get("amount", 1000)
    phone = data.get("phone") or data.get("accountnumber")

    if status in ["SUCCESS", "SUCCESSFUL", "COMPLETED", "200"]:
        user_id = PAYMENTS_DB.get(reference, ADMIN_ID)
        
        # Meseji kwenda kwa Admin
        admin_msg = (
            f"✅ **MUAMALA MPYA WA SONICPESA!**\n\n"
            f"📞 **Simu:** `{phone}`\n"
            f"💰 **Kiasi:** `{amount} TZS`\n"
            f"🆔 **Ref:** `{reference}`\n"
            f"👤 **User ID:** `{user_id}`"
        )
        
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": ADMIN_ID, "text": admin_msg, "parse_mode": "Markdown"})
        
        # Meseji kwenda kwa Mtumiaji
        if user_id != ADMIN_ID:
            user_msg = f"🎉 **Asante! Malipo yako ya TZS {amount} yamefanikiwa.**\nSasa unaweza kuendelea kutumia bot bila kikomo!"
            requests.post(url, json={"chat_id": user_id, "text": user_msg, "parse_mode": "Markdown"})

    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "SonicPesa Bot Webhook Server is Running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

Thread(target=run_flask, daemon=True).start()

# --- FUNCTION YA KUOMBA MALIPO SONICPESA ---
def request_sonicpesa_payment(phone_number, amount):
    url = "https://sonicpesa.com/api/v1/checkout"  # Njia kuu ya SonicPesa API
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
        return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- COMMAND: /lipa [namba_ya_simu] ---
async def lipa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "💳 **Malipo ya Wiki (SonicPesa):**\n"
            "Andika: `/lipa 0712345678`\n\n"
            "Gharama: **1,000 TZS** kwa wiki.",
            parse_mode="Markdown"
        )
        return

    phone = args[0].strip()
    if phone.startswith("+255"):
        phone = "0" + phone[4:]
    elif phone.startswith("255"):
        phone = "0" + phone[3:]

    msg = await update.message.reply_text(f"🔄 Inatuma ombi la malipo SonicPesa kwenda `{phone}`... Subiri popup kwenye simu.", parse_mode="Markdown")

    res = request_sonicpesa_payment(phone, 1000)

    if res.get("status") in [True, "success", "PENDING", 200]:
        reference = res.get("reference") or res.get("trans_id") or str(user_id)
        PAYMENTS_DB[reference] = str(user_id)
        await msg.edit_text("📱 **Popup imetumwa kwenye simu yako!**\nIngiza **PIN** yako kukamilisha muamala.")
    else:
        err_msg = res.get("message") or res.get("error") or "Imeshindikana kutuma ombi la malipo."
        await msg.edit_text(f"❌ **Hitilafu:** {err_msg}")

# --- FUNCTION YA BOT SEARCH & COMMANDS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 **Karibu kwenye Kadomovie Bot!**\n\n"
        "1️⃣ **Tafuta Muvi:** Andika jina la muvi (Mfano: `DJ Mjukuu`, `Babu DJ`).\n"
        "2️⃣ **Lipia:** Tumia command `/lipa 07xxxxxxxx` kulipia huduma.",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.message.text.strip()
    
    if str(user.id) != ADMIN_ID:
        try:
            admin_msg = f"🔔 **Mtumiaji:** {user.first_name} (@{user.username or 'No User'})\n🔍 **Ametafuta:** `{query}`"
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        except Exception:
            pass

    msg = await update.message.reply_text(f"🔍 Inatafuta muvi za '{query}'...")
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    results = []

    for page in range(1, 6):
        search_url = f"https://www.absalomfamily.com/?s={query}" if page == 1 else f"https://www.absalomfamily.com/page/{page}/?s={query}"
        try:
            res = requests.get(search_url, headers=headers, timeout=10)
            if res.status_code != 200: break
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for a_tag in soup.find_all('a'):
                title = a_tag.get_text().strip()
                href = a_tag.get('href', '')
                if query.lower() in title.lower() and href.startswith('http') and 'drive.google.com' not in href:
                    if not any(r['url'] == href for r in results) and len(title) > 3:
                        results.append({'title': title, 'url': href})
        except Exception:
            break

    if not results:
        await msg.edit_text(f"❌ Hakuna muvi iliyopatikana kwa '{query}'.")
        return

    await msg.edit_text(f"✅ Nimepata muvi {len(results)}! Inazituma zote...")

    for item in results:
        try:
            p_res = requests.get(item['url'], headers=headers, timeout=10)
            p_soup = BeautifulSoup(p_res.text, 'html.parser')

            drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', p_res.text)
            drive_text = drive_links[0].rstrip('.,;') if drive_links else "⚠️ Link haijapatikana"

            poster_url = None
            og_image = p_soup.find('meta', property='og:image')
            if og_image and og_image.get('content'): poster_url = og_image['content']

            caption = f"🎬 Muvi: {item['title']}\n\n📁 Download Link:\n{drive_text}"

            if poster_url:
                await update.message.reply_photo(photo=poster_url, caption=caption)
            else:
                await update.message.reply_text(caption)

            await asyncio.sleep(1.2)
        except Exception:
            continue

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start_command))
    app.add_handler(CommandHandler("lipa", lipa_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
