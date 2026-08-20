import os
import re
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Server ndogo ya kuijibu Render ili isifunge bot (Port Health Check)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ipo hai!")

    def log_message(self, format, *args):
        return  # Zuia spam kwenye logs

def run_health_check():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Anzisha server ya port kwenye background
Thread(target=run_health_check, daemon=True).start()

# Mipangilio ya Telegram Bot
TOKEN = os.getenv("BOT_TOKEN", "8641125457:AAGem16-Y8ekNisn8ZRtzIfHcrW7tMJzyj0")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Karibu! Tuma amri kutafuta muvi.\nMfano: /movie Rambo")

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("⚠️ Tafadhali andika jina la muvi. Mfano: /movie Rambo")
        return

    msg = await update.message.reply_text("🔍 Inatafuta mtandaoni...")
    search_url = f"https://www.absalomfamily.com/?s={query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        res = requests.get(search_url, headers=headers, timeout=15)
        drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', res.text)

        if drive_links:
            clean_link = drive_links[0].rstrip('.,;')
            await msg.edit_text(f"🎬 **Muvi:** {query.title()}\n\n📁 **Google Drive Link:**\n{clean_link}", parse_mode="Markdown")
        else:
            await msg.edit_text("❌ Samahani, muvi hii au link ya Google Drive haijapatikana.")
    except Exception as e:
        await msg.edit_text("⚠️ Hitilafu imetokea wakati wa kuchukua data.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("movie", search_movie))
    print("Bot na Web Server zipo hewani...")
    app.run_polling(drop_pending_updates=True)
