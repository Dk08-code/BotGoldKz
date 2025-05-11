import feedparser
import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.ext import ApplicationBuilder, ContextTypes
import sqlite3
from deep_translator import GoogleTranslator
import logging
from dotenv import load_dotenv
import os

# Загружаем переменные окружения из .env файла
load_dotenv()

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
conn = sqlite3.connect('news.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS sent_links (link TEXT PRIMARY KEY)''')
conn.commit()

def has_link(link):
    c.execute("SELECT 1 FROM sent_links WHERE link=?", (link,))
    return c.fetchone() is not None

def add_link(link):
    c.execute("INSERT INTO sent_links (link) VALUES (?)", (link,))
    conn.commit()

# Commodity keywords
KEYWORDS = ['золото', 'нефть', 'горнодобывающая', 'gold', 'oil', 'mining', 'commodities', 'metals', 'energy']

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

# English sources requiring translation
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
    # Add more scrapers for kegoc.kz, gov.kz, etc., as needed
}

# Функция для перевода текста
def translate_text(text, url):
    if url in ENGLISH_SOURCES:
        return GoogleTranslator(source='auto', target='ru').translate(text)
    return text

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
                    rt = translate_text(t, url)
                    txt = f"<b>{rt}</b>\n{l}"
                    # Заменить на реальную логику получения подписчиков
                    for uid in [-1008043165443]:  # Placeholder: implement get_subscribers()
                        await context.bot.send_message(chat_id=uid, text=txt, parse_mode='HTML')
                    add_link(l)
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")

# Bot setup
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = Bot(TELEGRAM_TOKEN)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.job_queue.run_repeating(fetch_and_post_news, interval=1800, first=0)
    app.run_polling()
