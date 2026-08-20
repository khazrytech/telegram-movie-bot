import os
import requests
from bs4 import BeautifulSoup
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

# Server ya kuizuia Render isifunge bot
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
    query = update.message.text.replace("/movie", "").strip()
    if not query:
        await update.message.reply_text("Andika jina la muvi/DJ.")
        return

    msg = await update.message.reply_text("🔍 Inatafuta...")
    search_url = f"https://www.absalomfamily.com/?s={query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Inatafuta links zote za Google Drive
        links = soup.find_all('a', href=lambda href: href and 'drive.google.com' in href)
        
        if links:
            reply = f"🎬 **Matokeo ya '{query}':**\n\n"
            for link in links[:5]: # Inaonyesha link 5 za kwanza
                reply += f"👉 {link['href']}\n"
            await msg.edit_text(reply)
        else:
            # DEBUGGING: Hapa tutaona nini kipo kwenye ukurasa kwenye logs za Render
            print(f"DEBUG: Hakuna link iliyopatikana. Preview: {response.text[:500]}")
            await msg.edit_text("❌ Sijapata link za Google Drive. Inawezekana hazipo kwenye ukurasa huu wa utafutaji.")
            
    except Exception as e:
        await msg.edit_text(f"⚠️ Hitilafu: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, search_movie))
    app.run_polling()
