import os
import json
import logging
import feedparser
import requests
from deep_translator import GoogleTranslator
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters



def extract_real_link(entry):
    # 1) пробуем entry.link
    link = entry.get('link', '')
    parsed = urllib.parse.urlparse(link)
    if link and 'biztoc.com' not in parsed.netloc and 'feedproxy.google' not in parsed.netloc:
        return link

    # 2) пробуем entry.id
    orig = entry.get('id', '')
    parsed = urllib.parse.urlparse(orig)
    if orig and 'biztoc.com' not in parsed.netloc:
        return orig

    # 3) пробуем все entry.links
    for lobj in entry.get('links', []):
        href = lobj.get('href', '')
        p = urllib.parse.urlparse(href)
        if href and 'biztoc.com' not in p.netloc and 'feedproxy.google' not in p.netloc:
            return href

    # 4) парсим HTML описания и берём первую <a href=…>
    desc = entry.get('description', '')
    if desc:
        soup = BeautifulSoup(desc, 'html.parser')
        a = soup.find('a', href=True)
        if a:
            return a['href']

    # 5) иначе возвращаем исходную ссылку
    return link
    
# ——————————————————————————————————————————————————————————
#            ЛОГИРОВАНИЕ
# ——————————————————————————————————————————————————————————
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——————————————————————————————————————————————————————————
#           НАСТРОЙКИ
# ——————————————————————————————————————————————————————————
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7826525577:AAGCtpXb49cwXAbJbvf0frofzAwslvQMl6c')
LINKS_FILE    = 'posted_links.json'
USERS_FILE    = 'subscribed_users.json'

# ключевые слова для фильтрации (в lower)
KEYWORDS      = ['золото', 'gold', 'серебро', 'silver', 'золота', 'серебра']
# сколько последних записей шлём при подписке
SEND_LAST_N   = 5

# RSS‑эндпойнты ваших источников:
RSS_FEEDS = [
    # 🇰🇿 Казахстан
    "https://kursiv.kz/rss",                 # Kursiv.kz — бизнес‑новости
    "https://informburo.kz/feed/",           # Informburo.kz — общий WordPress‑фид
    "https://kz.kursiv.media/feed/",         # Kursiv Media Kazakhstan
    "https://kapital.kz/rss",                # Kapital.kz — RSS
    "https://inbusiness.kz/ru/rss/all",      # Inbusiness.kz — все новости
    "https://finprom.kz/rss",                # Finprom.kz — статистика (если есть)
    "https://kegoc.kz/rss",                  # KEGOC — регуляторные обновления
    "https://gov.kz/rss",                    # Gov.kz — правительственные RSS

    # 🌐 Global
    "https://www.kitco.com/news/rss",                          # Kitco News
    "http://feeds.feedburner.com/reuters/businessNews",        # Reuters Business News
    "https://www.gold.org/news/rss",                           # World Gold Council
    "https://www.mining.com/feed/",                            # Mining.com
    "https://www.statista.com/rss",                            # Statista (общий RSS)
    "https://www.bloomberg.com/markets/economics/rss",         # Bloomberg Markets & Economics
    "https://www.ft.com/commodities?format=rss"                # FT Commodities
]

# ——————————————————————————————————————————————————————————
#            ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ——————————————————————————————————————————————————————————
def load_json(path):
    try:
        with open(path, 'r') as f: return set(json.load(f))
    except: return set()

def save_json(data, path):
    with open(path, 'w') as f: json.dump(list(data), f)

posted_links    = load_json(LINKS_FILE)
subscribed_users = load_json(USERS_FILE)

bot = Bot(token=TELEGRAM_TOKEN)
translator = GoogleTranslator(source='auto', target='ru')

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
    if uid not in subscribed_users:
        subscribed_users.add(uid)
        save_json(subscribed_users, USERS_FILE)
        await update.message.reply_text("Вы подписались! Отправляю последние новости…")
        for url in RSS_FEEDS:
            try:
                resp = requests.get(url, headers={'User-Agent':'Mozilla/5.0'})
                feed = feedparser.parse(resp.content)
                count = 0
                for entry in feed.entries:
                    t = entry.get('title','')
                    l = entry.get('link','')
                    if t and l and any(k in t.lower() for k in KEYWORDS):
                        # всегда переводим на русский
                        try:
                            rt = translator.translate(t)
                        except:
                            rt = t
                        await bot.send_message(uid, f"{rt}\n{l}")
                        count += 1
                        if count >= SEND_LAST_N: break
            except Exception as e:
                logger.error(f"Ошибка при отправке исторических новостей {url}: {e}")
    else:
        await update.message.reply_text("Вы уже подписаны.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in subscribed_users:
        subscribed_users.remove(uid)
        save_json(subscribed_users, USERS_FILE)
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
#        ФУНКЦИЯ ПАРСИНГА И РАССЫЛКИ НОВОСТЕЙ
# ——————————————————————————————————————————————————————————
async def fetch_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    logger.info("=== Запуск fetch_and_post_news ===")
    for url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers={'User-Agent':'Mozilla/5.0'})
            feed = feedparser.parse(resp.content)
            logger.info(f"[DEBUG] {url}: HTTP {resp.status_code}, entries={len(feed.entries)}")
            for entry in feed.entries:
                t = entry.get('title','')
                l = extract_real_link(entry)
                if not t or not l or l in posted_links: continue
                if any(k in t.lower() for k in KEYWORDS):
                    # переводим всегда на русский
                    try:
                        rt = translator.translate(t)
                    except:
                        rt = t
                    txt = f"{rt}\n{l}"
                    for uid in list(subscribed_users):
                        try: await bot.send_message(uid, txt)
                        except Exception as e: logger.error(f"Не отправлено {uid}: {e}")
                    posted_links.add(l)
            save_json(posted_links, LINKS_FILE)
        except Exception as e:
            logger.error(f"Ошибка фида {url}: {e}")

# ——————————————————————————————————————————————————————————
#             ЗАПУСК БОТА
# ——————————————————————————————————————————————————————————
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('subscribe', subscribe))
    app.add_handler(CommandHandler('unsubscribe', unsubscribe))
    app.add_handler(CommandHandler('news', news))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_once(fetch_and_post_news, when=1)
    app.job_queue.run_repeating(fetch_and_post_news, interval=1800, first=0)

    app.run_polling()
