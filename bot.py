import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Health Check kwa ajili ya Render Web Service
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_health_check():
    server = HTTPServer(("0.0.0.0", int(os.getenv("PORT", 8080))), HealthCheckHandler)
    server.serve_forever()

Thread(target=run_health_check, daemon=True).start()

TOKEN = os.getenv("BOT_TOKEN", "8641125457:AAGem16-Y8ekNisn8ZRtzIfHcrW7tMJzyj0")
ADMIN_ID = "1846737920"  # ID Yako ya Telegram
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") # Sio lazima, lakini ukiiweka Render itajibu maswali kwa akili zaidi

# Mfumo wa kujibu maswali ya kawaida (Chat AI)
def ask_ai(prompt):
    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data['candidates'][0]['content']['parts'][0]['text']
    except Exception:
        pass
    return None

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.message.text.strip()
    
    first_name = user.first_name or "Mtumiaji"
    username = f"@{user.username}" if user.username else "Hana Username"
    user_id = user.id

    # 1. TUMA TAARIFA KWENYE TELEGRAM YAKO IKITUMIWA NA MTU MWINGINE
    if str(user_id) != ADMIN_ID:
        try:
            admin_msg = (
                f"🔔 **Mtumiaji Mpya Kwenye Bot!**\n\n"
                f"👤 **Jina:** {first_name}\n"
                f"🏷️ **Username:** {username}\n"
                f"🆔 **ID:** `{user_id}`\n"
                f"🔍 **Ujumbe:** `{query}`"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Hitilafu ya kutuma taarifa kwa Admin: {e}")

    # 2. SALAMU NA MASWALI YA KAWAIDA
    greetings = ['mambo', 'habari', 'hello', 'hi', 'vip', 'niaje', 'xambo', 'mambo vipi', 'shikamoo']
    if query.lower() in greetings:
        reply = ask_ai(query) or f"Jambo {first_name}! Mimi ni Kadomovie Bot. Unaweza kuniuliza maswali yoyote au kunitumia jina la muvi (mfano: 'DJ Mjukuu', 'Babu DJ') ili nikutafutie muvi na links za ku-download!"
        await update.message.reply_text(reply)
        return

    msg = await update.message.reply_text(f"🔍 Inatafuta kurasa zote kupata muvi za '{query}'...")

    # 3. UTAFUTAJI WA KURASA NYINGI (PAGINATION) ILI KUPATA SEASON ZOTE (1-8, 1-13 N.K.)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    results = []

    for page in range(1, 6):  # Inasoma hadi Kurasa 5 za tovuti ili isikose season yoyote
        search_url = f"https://www.absalomfamily.com/?s={query}" if page == 1 else f"https://www.absalomfamily.com/page/{page}/?s={query}"

        try:
            res = requests.get(search_url, headers=headers, timeout=10)
            if res.status_code != 200:
                break
            
            soup = BeautifulSoup(res.text, 'html.parser')
            found_in_page = False

            for a_tag in soup.find_all('a'):
                title = a_tag.get_text().strip()
                href = a_tag.get('href', '')
                if query.lower() in title.lower() and href.startswith('http') and 'drive.google.com' not in href:
                    if not any(r['url'] == href for r in results) and len(title) > 3:
                        results.append({'title': title, 'url': href})
                        found_in_page = True

            if not found_in_page and page > 1:
                break
        except Exception:
            break

    # 4. KAMA HAKUNA MUVI ILIYOPATIKANA, JIBU KAMA AI CHATBOT
    if not results:
        ai_reply = ask_ai(query)
        if ai_reply:
            await msg.edit_text(ai_reply)
        else:
            await msg.edit_text(f"❌ Sijapata muvi wala jibu la '{query}'. Jaribu kuandika vizuri jina la muvi au swali lako!")
        return

    await msg.edit_text(f"✅ Nimepata muvi/seasons {len(results)}! Inazituma zote zikiwa na poster na links...")

    # 5. TUMA MUVI ZOTE ZILIZOPATIKANA BILA LIMIT
    for item in results:
        post_url = item['url']
        try:
            p_res = requests.get(post_url, headers=headers, timeout=10)
            p_soup = BeautifulSoup(p_res.text, 'html.parser')

            # Google Drive Link
            drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', p_res.text)
            drive_text = drive_links[0].rstrip('.,;') if drive_links else "⚠️ Link ya Drive haijapatikana"

            # Poster Image URL
            poster_url = None
            og_image = p_soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                poster_url = og_image['content']
            else:
                img_tag = p_soup.find('img')
                if img_tag and img_tag.get('src'):
                    poster_url = img_tag['src']

            caption = f"🎬 Muvi: {item['title']}\n\n📁 Download Link:\n{drive_text}"

            if poster_url:
                try:
                    await update.message.reply_photo(photo=poster_url, caption=caption)
                except Exception:
                    await update.message.reply_text(caption)
            else:
                await update.message.reply_text(caption)

            await asyncio.sleep(1.2)  # Inalinda bot isifungiwe na Telegram

        except Exception:
            continue

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
