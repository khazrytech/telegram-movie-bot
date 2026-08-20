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

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    msg = await update.message.reply_text(f"🔍 Inatafuta muvi zote za '{query}'...")

    search_url = f"https://www.absalomfamily.com/?s={query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        res = requests.get(search_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        results = []
        for a_tag in soup.find_all('a'):
            title = a_tag.get_text().strip()
            href = a_tag.get('href', '')
            if query.lower() in title.lower() and href.startswith('http') and 'drive.google.com' not in href:
                if not any(r['url'] == href for r in results) and len(title) > 3:
                    results.append({'title': title, 'url': href})

        if not results:
            await msg.edit_text(f"❌ Hakuna muvi iliyopatikana kwa '{query}'.")
            return

        await msg.edit_text(f"✅ Nimepata muvi {len(results)}! Inazituma zote kwa mtiririko (subiri kidogo)...")

        # Inachukua muvi ZOTE zilizopatikana (hakuna kikomo cha 4 tena)
        for item in results:
            post_url = item['url']
            try:
                p_res = requests.get(post_url, headers=headers, timeout=10)
                p_soup = BeautifulSoup(p_res.text, 'html.parser')

                # 1. Google Drive Link
                drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', p_res.text)
                drive_text = drive_links[0].rstrip('.,;') if drive_links else "⚠️ Link ya Drive haijapatikana"

                # 2. Poster Image URL
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
                
                # MUHIMU: Tunaiwekea bot mapumziko ya sekunde 1.5 kuzuia Telegram isifungie bot kwa kutuma meseji nyingi (Spam limits)
                await asyncio.sleep(1.5)

            except Exception:
                continue

    except Exception as e:
        await update.message.reply_text(f"⚠️ Hitilafu: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    app.run_polling()
