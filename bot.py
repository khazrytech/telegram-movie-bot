import os
import re
import requests
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Server ndogo ya kuijibu Render ili isifunge bot
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot ipo hai!")

    def log_message(self, format, *args):
        return

def run_health_check():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

Thread(target=run_health_check, daemon=True).start()

TOKEN = os.getenv("BOT_TOKEN", "8641125457:AAGem16-Y8ekNisn8ZRtzIfHcrW7tMJzyj0")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Karibu! Andika jina la muvi au DJ unayemtafuta.\nMfano: babu dj au Rambo")

async def search_movie_logic(update: Update, query: str):
    query = query.strip()
    if not query:
        await update.message.reply_text("⚠️ Tafadhali andika jina la muvi au DJ. Mfano: babu dj")
        return

    msg = await update.message.reply_text(f"🔍 Inatafuta '{query}' mtandaoni...")
    search_url = f"https://www.absalomfamily.com/?s={query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        res = requests.get(search_url, headers=headers, timeout=15)
        drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', res.text)

        if drive_links:
            clean_link = drive_links[0].rstrip('.,;')
            await msg.edit_text(f"🎬 **Matokeo ya:** {query.title()}\n\n📁 **Google Drive Link:**\n{clean_link}", parse_mode="Markdown")
        else:
            await msg.edit_text(f"❌ Samahani, hakuna matokeo ya Google Drive link ya '{query}'.")
    except Exception as e:
        await msg.edit_text("⚠️ Hitilafu imetokea wakati wa kuchukua data.")

# Inapokea ujumbe wowote wa maandishi (mfano: babu dj au /babu dj)
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Kama mtumiaji ameweka alama ya slash (/) iondoe
    if text.startswith("/"):
        text = text[1:]
    await search_movie_logic(update, text)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))
    app.add_handler(MessageHandler(filters.COMMAND, handle_all_messages))
    
    print("Bot na Web Server zipo hewani...")
    app.run_polling(drop_pending_updates=True)
