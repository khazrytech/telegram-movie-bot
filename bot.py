import os
import requests
from bs4 import BeautifulSoup
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Health check kwa Render
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
    msg = await update.message.reply_text(f"🔍 Inatafuta chochote chenye '{query}'...")
    
    search_url = f"https://www.absalomfamily.com/?s={query}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Tunatafuta matokeo yote ya 'h2' ambayo mara nyingi yana vichwa vya muvi
        results = soup.find_all('h2')
        
        # Tunachuja ili kuondoa vichwa visivyo vya muvi (kama 'Search')
        found_items = []
        for res in results:
            text = res.get_text().strip()
            if text and len(text) > 5:
                found_items.append(text)
        
        if found_items:
            reply = f"✅ Nimepata matokeo haya kwa '{query}':\n\n"
            for item in found_items[:10]: # Inaonyesha 10 ya kwanza
                reply += f"👉 {item}\n"
            await msg.edit_text(reply)
        else:
            # Kama haijapata kwa h2, jaribu kutafuta link zote za kawaida
            links = soup.find_all('a')
            found_links = []
            for a in links:
                if query.lower() in a.get_text().lower() and len(a.get_text()) > 5:
                    found_links.append(a.get_text().strip())
            
            if found_links:
                reply = f"✅ Nimepata link hizi zenye '{query}':\n\n"
                for item in set(found_links[:10]):
                    reply += f"👉 {item}\n"
                await msg.edit_text(reply)
            else:
                await msg.edit_text(f"❌ Samahani, bot haijaona chochote chenye jina '{query}' kwenye hiyo website. Inawezekana website ina ulinzi.")
            
    except Exception as e:
        await msg.edit_text(f"⚠️ Hitilafu: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, search_movie))
    app.run_polling()
