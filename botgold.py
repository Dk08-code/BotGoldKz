import os
import logging
import urllib.parse
import sqlite3
import re
from contextlib import closing

import feedparser
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

# ——————————————————————————————————————————————————————————
#            НАСТРОЙКИ БД
# ——————————————————————————————————————————————————————————
DB_PATH = 'botdata.sqlite'

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS posted_links (
                link TEXT PRIMARY KEY
            )
        ''')
        conn.commit()

# ——————————————————————————————————————————————————————————
#         РАБОТА С БАЗОЙ (SQLite)
# ——————————————————————————————————————————————————————————
def add_subscriber(chat_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('INSERT OR IGNORE INTO subscribers(chat_id) VALUES(?)', (chat_id,))
        conn.commit()

def remove_subscriber(chat_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('DELETE FROM subscribers WHERE chat_id = ?', (chat_id,))
        conn.commit()

def get_subscribers() -> list[int]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute('SELECT chat_id FROM subscribers')
        return [row[0] for row in cur]

def has_link(link: str) -> bool:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute('SELECT 1 FROM posted_links WHERE link = ?', (link,))
        return cur.fetchone() is not None

def add_link(link: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('INSERT OR IGNORE INTO posted_links(link) VALUES(?)', (link,))
        conn.commit()

# ——————————————————————————————————————————————————————————
#            ЛОГИРОВАНИЕ
# ——————————————————————————————————————————————————————————
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————
#           НАСТРОЙКИ БОТА
# ——————————————————————————————————————————————————————————
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7826525577:AAGCtpXb49cwXAbJbvf0frofzAwslvQMl6c')

KEYWORDS = ['золото', 'gold', 'серебро', 'silver', 'золота', 'серебра']
SEND_LAST_N = 5
RSS_FEEDS = [
    "https://kursiv.kz/rss",
    "https://informburo.kz/feed/",
    "https://kz.kursiv.media/feed/",
    "https://kapital.kz/rss",
    "https://inbusiness.kz/ru/rss/all",
    "https://finprom.kz/rss",
    "https://kegoc.kz/rss",
    "https://gov.kz/rss",
    "https://www.kitco.com/news/rss",
    "http://feeds.feedburner.com/reuters/businessNews",
    "https://www.gold.org/news",
    "https://www.mining.com/feed/",
    "https://www.statista.com/rss",
    "https://www.bloomberg.com/markets/economics/rss",
    "https://www.ft.com/commodities?format=rss"
]

bot = Bot(token=TELEGRAM_TOKEN)
translator = GoogleTranslator(source='auto', target='ru')

# ——————————————————————————————————————————————————————————
#       ФУНКЦИЯ ФИЛЬТРАЦИИ ССЫЛОК
# ——————————————————————————————————————————————————————————
def extract_real_link(entry):
    def is_valid(link: str) -> bool:
        if not link:
            return False
        if any(domain in link for domain in ['biztoc.com', 'feedproxy.google', 'rss']):
            return False
        if re.fullmatch(r'https?://[^/]+/?', link):  # главная страница
            return False
        return True

    candidates = [
        entry.get('link', ''),
        entry.get('id', '')
    ]

    for lobj in entry.get('links', []):
        candidates.append(lobj.get('href', ''))

    desc = entry.get('description', '')
    if desc:
        soup = BeautifulSoup(desc, 'html.parser')
        a = soup.find('a', href=True)
        if a:
            candidates.append(a['href'])

    for c in candidates:
        if is_valid(c):
            return c
    return ''

# ——————————————————————————————————————————————————————————
#            КОМАНДЫ БОТА
# ——————————————————————————————————————————————————————————
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот новостей.\n"
        "/subscribe — подписаться\n"
        "/unsubscribe — отписаться\n"
        "/news — получить новости сейчас"
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in get_subscribers():
        add_subscriber(uid)
        await update.message.reply_text("Вы подписались! Отправляю последние новости…")
        count = 0
        for url in RSS_FEEDS:
            try:
                resp = requests.get(url, headers={'User-Agent':'Mozilla/5.0'})
                feed = feedparser.parse(resp.content)
                for entry in feed.entries:
                    t = entry.get('title','')
                    l = extract_real_link(entry)
                    if not t or not l: continue
                    if any(k in t.lower() for k in KEYWORDS):
                        rt = translator.translate(t)
                        await bot.send_message(uid, f"{rt}\n{l}")
                        count += 1
                        if count >= SEND_LAST_N:
                            return
            except Exception as e:
                logger.error(f"Ошибка при отправке исторических новостей {url}: {e}")
    else:
        await update.message.reply_text("Вы уже подписаны.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in get_subscribers():
        remove_subscriber(uid)
        await update.message.reply_text("Вы отписались.")
    else:
        await update.message.reply_text("Вы не были подписаны.")

async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ищу новости…")
    await fetch_and_post_news(context)
    await update.message.reply_text("Готово.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe(update, context)

# ——————————————————————————————————————————————————————————
#         РАССЫЛКА СВЕЖИХ НОВОСТЕЙ
# ——————————————————————————————————————————————————————————
async def fetch_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    logger.info("=== Запуск fetch_and_post_news ===")
    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers={'User-Agent':'Mozilla/5.0'})
            feed = feedparser.parse(resp.content)
            for entry in feed.entries:
                t = entry.get('title','')
                l = extract_real_link(entry)
                if not t or not l or has_link(l): continue
                if any(k in t.lower() for k in KEYWORDS):
                    rt = translator.translate(t)
                    txt = f"{rt}\n{l}"
                    for uid in get_subscribers():
                        try:
                            await bot.send_message(uid, txt)
                        except Exception as e:
                            logger.error(f"Не отправлено {uid}: {e}")
                    add_link(l)
        except Exception as e:
            logger.error(f"Ошибка фида {url}: {e}")

# ——————————————————————————————————————————————————————————
#             ЗАПУСК БОТА
# ——————————————————————————————————————————————————————————
if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('subscribe', subscribe))
    app.add_handler(CommandHandler('unsubscribe', unsubscribe))
    app.add_handler(CommandHandler('news', news))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_once(fetch_and_post_news, when=1)
    app.job_queue.run_repeating(fetch_and_post_news, interval=1800, first=0)

    app.run_polling()
