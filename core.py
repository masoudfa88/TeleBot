import logging
import os
import sys
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder
import json

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

load_dotenv(resource_path(".env"))

if getattr(sys, 'frozen', False):
    log_path = os.path.join(os.path.dirname(sys.executable), "bot_logs.log")
else:
    log_path = "bot_logs.log"
    
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# بررسی اینکه آیا قبلاً FileHandler توسط فایل دیگری اضافه شده است یا خیر
if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
    formatter = logging.Formatter("[ %(asctime)s: %(levelname)-8s ] %(name)-20s - %(message)s")
    
    # متصل کردن فایل لاگ
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # نمایش در ترمینال (در صورت نبود گرافیک)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

LOGGER = logging.getLogger(__name__)
httpx_logger = logging.getLogger('httpx')
httpx_logger.setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    LOGGER.error("No BOT_TOKEN token provided!")
    sys.exit(1)
    
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# --- ساخت نمونه اصلی ربات با در نظر گرفتن پروکسی ---
builder = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .connect_timeout(60.0)      # حداکثر زمان برای اتصال به سرور (ثانیه)
    .read_timeout(300.0)        # حداکثر زمان برای دریافت اطلاعات (۵ دقیقه)
    .write_timeout(300.0)       # حداکثر زمان برای آپلود فایل‌ها (۵ دقیقه)
)

def get_config_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "proxy_config.json")
    return os.path.join(os.path.abspath("."), "proxy_config.json")

config_path = get_config_path()
proxy_enable = False

if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        proxy_enable = config.get("PROXY_ENABLE", False)
        proxy_type = config.get("PROXY_TYPE", "socks5")
        proxy_ip = config.get("PROXY_IP", "127.0.0.1")
        proxy_port = config.get("PROXY_PORT", "10808")

if proxy_enable:
    proxy_url = f"{proxy_type}://{proxy_ip}:{proxy_port}"
    builder = builder.proxy_url(proxy_url).get_updates_proxy_url(proxy_url)
    LOGGER.info(f"Using Proxy for PTB: {proxy_url}")

bot = builder.build()