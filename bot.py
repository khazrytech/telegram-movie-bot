import os
import re
import requests
from bs4 import BeautifulSoup
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Health Check kwa Render Web Service
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
    msg = await update.message.reply_text(f"🔍 Inatafuta '{query}'...")

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

        if results:
            keyboard = []
            context.user_data['movies'] = {}

            for i, item in enumerate(results[:8]):
                movie_id = f"m_{i}"
                context.user_data['movies'][movie_id] = item
                btn_text = item['title'][:35] + "..." if len(item['title']) > 35 else item['title']
                keyboard.append([InlineKeyboardButton(f"🎬 {btn_text}", callback_data=movie_id)])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await msg.edit_text(f"✅ **Nimepata muvi hizi. Bonyeza unayotaka:**", parse_mode="Markdown", reply_markup=reply_markup)
        else:
            await msg.edit_text(f"❌ Hakuna muvi iliyopatikana kwa '{query}'.")

    except Exception as e:
        await msg.edit_text(f"⚠️ Hitilafu: {str(e)}")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔍 Inachukua Poster & Drive Link...")

    movie_id = query.data
    movies = context.user_data.get('movies', {})
    selected_movie = movies.get(movie_id)

    if not selected_movie:
        await query.message.reply_text("⚠️ Chaguo limekwisha muda wake, tafadhali andika jina la muvi tena.")
        return

    post_url = selected_movie['url']
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        res = requests.get(post_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')

        # 1. Tafuta Google Drive Link
        drive_links = re.findall(r'https://drive\.google\.com/[^\s"\'<>]+', res.text)
        
        # 2. Tafuta Poster Image URL
        poster_url = None
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            poster_url = og_image['content']
        else:
            img_tag = soup.find('img')
            if img_tag and img_tag.get('src'):
                poster_url = img_tag['src']

        if drive_links:
            clean_link = drive_links[0].rstrip('.,;')
            caption_text = f"🎬 **Muvi:** {selected_movie['title']}\n\n📁 **Google Drive Link:**\n{clean_link}"
            
            # Tuma picha ikiwa na caption kama poster ipo
            if poster_url:
                try:
                    await query.message.reply_photo(
                        photo=poster_url,
                        caption=caption_text,
                        parse_mode="Markdown"
                    )
                except Exception:
                    await query.message.reply_text(caption_text, parse_mode="Markdown")
            else:
                await query.message.reply_text(caption_text, parse_mode="Markdown")
        else:
            await query.message.reply_text(f"❌ Link ya Google Drive haijapatikana ndani ya ukurasa wa '{selected_movie['title']}'.")

    except Exception as e:
        await query.message.reply_text(f"⚠️ Hitilafu wakati wa kuchukua data: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    app.add_handler(CallbackQueryHandler(button_click))
    app.run_polling()
