import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
import sqlite3
from googletrans import Translator
import logging

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize translator
translator = Translator()

# Commodity keywords
KEYWORDS = ['золото', 'горнодобывающая', 'gold', 'mining', 'commodities', 'metals']

# RSS sources
RSS_SOURCES = {
    'https://kursiv.kz': 'https://kursiv.kz/rss',
    'https://informburo.kz': 'https://informburo.kz/rss',
    'https://kz.kursiv.media': 'https://kz.kursiv.media/rss',
    'https://kapital.kz': 'https://kapital.kz/rss',
    'https://inbusiness.kz': 'https://inbusiness.kz/rss',
    'https://www.kitco.com': 'https://www.kitco.com/rss',
    'https://www.reuters.com': 'https://www.reuters.com/arc/outboundfeeds/commodities/',
    'https://www.gold.org': 'https://www.gold.org/news/rss',
    'https://mining.com': 'https://mining.com/feed',
}

ENGLISH_SOURCES = ['https://www.kitco.com', 'https://www.reuters.com', 'https://www.gold.org', 'https://mining.com']

# Custom scrapers
def scrape_finprom():
    url = 'https://finprom.kz/ru/news'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    articles = []
    for item in soup.find_all('div', class_='news-item'):
        title_tag = item.find('h3')
        if title_tag:
            title = title_tag.text.strip()
            link_tag = item.find('a')
            if link_tag and 'href' in link_tag.attrs:
                link = 'https://finprom.kz' + link_tag['href']
                articles.append({'title': title, 'link': link})
    return articles

SITE_SCRAPERS = {
    'https://finprom.kz': scrape_finprom,
}

# Database helpers
def get_db_connection():
    return sqlite3.connect('news.db')

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sent_links (link TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS subscribers (user_id INTEGER PRIMARY KEY)''')
        conn.commit()

def has_link(link):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM sent_links WHERE link=?", (link,))
        return c.fetchone() is not None

def add_link(link):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO sent_links (link) VALUES (?)", (link,))
        conn.commit()

def get_subscribers():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM subscribers")
        return [row[0] for row in c.fetchall()]

def add_subscriber(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO subscribers (user_id) VALUES (?)", (user_id,))
        conn.commit()

def remove_subscriber(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM subscribers WHERE user_id=?", (user_id,))
        conn.commit()

# Telegram handlers
async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    add_subscriber(user_id)
    await context.bot.send_message(chat_id=user_id, text="Вы подписались на новости.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    remove_subscriber(user_id)
    await context.bot.send_message(chat_id=user_id, text="Вы отписались от новостей.")

async def fetch_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    all_sources = list(RSS_SOURCES.keys()) + list(SITE_SCRAPERS.keys())
    for url in all_sources:
        try:
            if url in RSS_SOURCES:
                feed = feedparser.parse(RSS_SOURCES[url])
                articles = [{'title': entry.title, 'link': entry.link} for entry in feed.entries]
            else:
                articles = SITE_SCRAPERS[url]()

            for article in articles:
                t = article['title']
                l = article['link']
                if not t or not l or has_link(l):
                    continue
                if any(k in t.lower() for k in KEYWORDS):
                    rt = translator.translate(t, dest='ru').text if url in ENGLISH_SOURCES else t
                    txt = f"<b>{rt}</b>\n{l}"
                    for uid in get_subscribers():
                        await context.bot.send_message(chat_id=uid, text=txt, parse_mode='HTML')
                    add_link(l)
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")

# Token and start
TELEGRAM_TOKEN = '7826525577:AAGCtpXb49cwXAbJbvf0frofzAwslvQMl6c'

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))

    app.job_queue.run_repeating(fetch_and_post_news, interval=1800, first=0)
    app.run_polling()
