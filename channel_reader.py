import os
import asyncio
import httpx
import socks 
from collections import deque
from telethon.sync import TelegramClient, events
from telethon.sessions import StringSession
from dotenv import load_dotenv
from telegram import InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError
from core import bot, LOGGER
from database import get_license_subscribers, get_remove_words, get_channel_title, ALBUM_CAPTIONS, get_mappings
from database import add_to_cache, get_recent_cache, cleanup_cache, get_forbidden_words
from database import get_target_by_id, get_bale_targets, get_eitaa_targets, increment_stat, get_users_of_license
from telegram.constants import ParseMode
import sys
import json
import re
import time
import io
from PIL import Image
import imagehash
from thefuzz import fuzz
from bale_sender import send_to_bale, send_album_to_bale
from eitaa_sender import send_to_eitaa, send_album_to_eitaa, get_driver as get_eitaa_driver

telegram_queue = asyncio.Queue()
bale_queue = asyncio.Queue()
eitaa_queue = asyncio.Queue()

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

load_dotenv(resource_path(".env"))

api_id = int(os.getenv("API_ID", 0))
api_hash = os.getenv("API_HASH", "")
phone_number = os.getenv("PHONE_NUMBER", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
session_string = os.getenv("SESSION_STRING", "")

DIRECT_COPY = False 
TEMP_DIR = resource_path("temp_downloads")
os.makedirs(TEMP_DIR, exist_ok=True)

def get_config_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "proxy_config.json")
    return os.path.join(os.path.abspath("."), "proxy_config.json")

proxy_enable = False
proxy_settings = None
config_path = get_config_path()

if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        proxy_enable = config.get("PROXY_ENABLE", False)
        proxy_type_str = config.get("PROXY_TYPE", "socks5").lower()
        proxy_ip = config.get("PROXY_IP", "127.0.0.1")
        proxy_port = int(config.get("PROXY_PORT", "10808"))

if proxy_enable:
    p_type = socks.SOCKS5
    if proxy_type_str == "http": p_type = socks.HTTP
    elif proxy_type_str == "socks4": p_type = socks.SOCKS4
    proxy_settings = (p_type, proxy_ip, proxy_port)

client_params = {
    "api_id": api_id,
    "api_hash": api_hash,
    "proxy": proxy_settings,
    "connection_retries": None,
    "request_retries": 5,
    "flood_sleep_threshold": 60,
    "auto_reconnect": True
}

client = TelegramClient(StringSession(session_string) if session_string else "session_name", **client_params)

processed_albums = deque(maxlen=200)
# اجرای پردازش سنگین در ترد جداگانه
def calculate_phash(thumb_bytes):
    img = Image.open(io.BytesIO(thumb_bytes))
    return str(imagehash.phash(img))

# تابع حذف امن فایل (با Retry برای حل مشکل درگیری در ویندوز)
async def safe_remove_file(file_path):
    for _ in range(4):
        try:
            await asyncio.to_thread(os.remove, file_path)
            break
        except OSError:
            await asyncio.sleep(1.5) # صبر برای آزاد شدن فایل
            
async def track_task(coro, user_id, source_id, stat_type):
    success = await coro
    if success:
        await increment_stat(user_id, source_id, stat_type, 1)
# =======================================================
# توابع کمکی برای ارسال به همراه Retry (غیر مسدود کننده)
# =======================================================

async def send_tg_album_with_retry(tgt, downloaded_files, final_auto_caption):
    for attempt in range(3):
        opened_files = []
        try:
            media_group = []
            caption_added = False
            for item in downloaded_files:
                m, path = item["msg"], item["path"]
                curr_cap = final_auto_caption if not caption_added else None
                f = open(path, 'rb')
                opened_files.append(f)
                if m.photo:
                    media_group.append(InputMediaPhoto(media=f, caption=curr_cap))
                    caption_added = True
                elif m.video:
                    media_group.append(InputMediaVideo(media=f, caption=curr_cap))
                    caption_added = True
            if media_group:
                await bot.bot.send_media_group(chat_id=tgt, media=media_group, read_timeout=300.0, write_timeout=300.0)
            return True
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Album Timeout for {tgt} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: 
                LOGGER.error(f"❌ Failed to send album to {tgt}.")
                return False            
            else: await asyncio.sleep(3)
        finally:
            for f in opened_files: f.close()
    return False

async def send_tg_manual_album_with_retry(user_id, downloaded_files, clean_caption, ch_title, bot_api_from_chat_id):
    for attempt in range(3):
        opened_files = []
        try:
            media_group = []
            caption_added = False
            for item in downloaded_files:
                m, path = item["msg"], item["path"]
                curr_cap = clean_caption if not caption_added else None
                f = open(path, 'rb')
                opened_files.append(f)
                if m.photo:
                    media_group.append(InputMediaPhoto(media=f, caption=curr_cap))
                    caption_added = True
                elif m.video:
                    media_group.append(InputMediaVideo(media=f, caption=curr_cap))
                    caption_added = True
            if media_group:
                sent_msgs = await bot.bot.send_media_group(chat_id=user_id, media=media_group, read_timeout=300.0, write_timeout=300.0)
                if sent_msgs:
                    start_id, end_id = sent_msgs[0].message_id, sent_msgs[-1].message_id
                    ALBUM_CAPTIONS[start_id] = clean_caption
                    reply_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"📢 از کانال: {ch_title}", callback_data="ignore")],
                        [InlineKeyboardButton("📤 انتشار در مقصدهای تاییدشده", callback_data=f"pub_alb_{start_id}_{end_id}_{bot_api_from_chat_id}")],
                        [InlineKeyboardButton("✏️ تغییر و انتشار", callback_data=f"edit_alb_{start_id}_{end_id}_{bot_api_from_chat_id}")]
                    ])
                    await bot.bot.send_message(chat_id=user_id, text="👆 عملیات برای آلبوم بالا:", reply_markup=reply_markup)
            return True
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Manual Album Error for {user_id} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: 
                LOGGER.error(f"❌ Failed manual album to {user_id}.")
                return False
            else: await asyncio.sleep(3)
        finally:
            for f in opened_files: f.close()
    return False

async def send_tg_single_with_retry(tgt, file_path, file_type, text_caption, msg_obj=None):
    for attempt in range(3):
        try:
            if file_path:
                with open(file_path, 'rb') as f:
                    if file_type == 'photo': await bot.bot.send_photo(chat_id=tgt, photo=f, caption=text_caption, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'video': await bot.bot.send_video(chat_id=tgt, video=f, caption=text_caption, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'audio': await bot.bot.send_audio(chat_id=tgt, audio=f, caption=text_caption, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'document':
                        fname = msg_obj.file.name if (msg_obj and hasattr(msg_obj, 'file') and msg_obj.file) else "document.file"
                        await bot.bot.send_document(chat_id=tgt, document=f, filename=fname, caption=text_caption, read_timeout=300.0, write_timeout=300.0)
            else:
                await bot.bot.send_message(chat_id=tgt, text=text_caption)
            return True
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Single Timeout for {tgt} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: 
                LOGGER.error(f"❌ Failed single msg to {tgt}.")
                return False
            else: await asyncio.sleep(3)
    return False

async def send_tg_manual_single_with_retry(user_id, file_path, file_type, clean_text, ch_title, bot_api_from_chat_id, msg_obj=None):
    for attempt in range(3):
        try:
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📢 از کانال: {ch_title}", callback_data="ignore")],
                [InlineKeyboardButton("📤 انتشار در مقصدهای تاییدشده", callback_data=f"pub_sgl_{bot_api_from_chat_id}")],
                [InlineKeyboardButton("✏️ تغییر و انتشار", callback_data=f"edit_sgl_{bot_api_from_chat_id}")]
            ])
            if file_path:
                with open(file_path, 'rb') as f:
                    if file_type == 'photo': await bot.bot.send_photo(chat_id=user_id, photo=f, caption=clean_text, reply_markup=reply_markup, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'video': await bot.bot.send_video(chat_id=user_id, video=f, caption=clean_text, reply_markup=reply_markup, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'audio': await bot.bot.send_audio(chat_id=user_id, audio=f, caption=clean_text, reply_markup=reply_markup, read_timeout=300.0, write_timeout=300.0)
                    elif file_type == 'document':
                        fname = msg_obj.file.name if (msg_obj and hasattr(msg_obj, 'file') and msg_obj.file) else "document.file"
                        await bot.bot.send_document(chat_id=user_id, document=f, filename=fname, caption=clean_text, reply_markup=reply_markup, read_timeout=300.0, write_timeout=300.0)
            else:
                await bot.bot.send_message(chat_id=user_id, text=clean_text, reply_markup=reply_markup)
            return True
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Manual Single Error for {user_id} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: 
                LOGGER.error(f"❌ Failed manual single msg to {user_id}.")
                return False
            else: await asyncio.sleep(3)
    return False
# =======================================================
# توابع فیلترینگ و اجرای اصلی برنامه
# =======================================================

async def apply_filters(text: str, license_key: str):
    if not text: return text
    
    # اولویت ۱: حذف آیدی‌ها
    text = re.sub(r'@[a-zA-Z0-9_]+', '', text)
    
    # اولویت ۲: حذف لینک‌های پیشرفته
    url_pattern = r'(?i)(?:https?://|www\.)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?'
    text = re.sub(url_pattern, '', text)
    
    bad_words = await get_remove_words(license_key)
    if bad_words:
        bad_words.sort(key=len, reverse=True)
        for word in bad_words:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            text = pattern.sub("", text)
    
    # مرتب‌سازی فاصله‌های اضافی
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'(?:[^\w.!?،؛)\]"\'»]|\s)+$', '', text)
    
    return text.strip()

def normalize_text(text: str) -> str:
    if not text: return ""
    text = re.sub(r'http\S+|www.\S+', '', text)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\d+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_preview(text, n=4):
    if not text: return "[بدون متن]"
    words = str(text).split()
    return " ".join(words[:n]) + ("..." if len(words) > n else "")

async def check_target_duplicate(license_key: str, target_id: str, filtered_text: str, unique_id: str, current_phash_str: str) -> bool:
    norm_text = normalize_text(filtered_text)
    # اضافه شدن license_key به فراخوانی دیتابیس
    recent_posts = await get_recent_cache(license_key, str(target_id)) 
    
    if norm_text and len(norm_text) > 15:
        for _, _, cached_text in recent_posts:
            if cached_text and len(cached_text) > 15:
                if fuzz.ratio(norm_text, cached_text) >= 60: return True 

    if unique_id:
        for cached_uid, _, _ in recent_posts:
            if cached_uid == unique_id: return True
                
    if current_phash_str:
        current_phash = imagehash.hex_to_hash(current_phash_str)
        for _, cached_phash, _ in recent_posts:
            if cached_phash:
                cached_hash_obj = imagehash.hex_to_hash(cached_phash)
                if current_phash - cached_hash_obj <= 5: return True 
    return False

async def periodic_cache_cleanup():
    while True:
        await asyncio.sleep(3600)
        try:
            await cleanup_cache()
            LOGGER.info("🧹 کش پیام‌های قدیمی (بیش از 3 ساعت) پاکسازی شد.")
        except Exception as e:
            LOGGER.error(f"خطا در پاکسازی کش: {e}")
# =======================================================
# کارگرهای پس‌زمینه (Workers) برای ارسال پیام‌ها
# =======================================================
async def telegram_worker():
    while True:
        task = await telegram_queue.get()
        try:
            if task['action'] == 'single':
                success = await send_tg_single_with_retry(task['tgt'], task['file_path'], task['file_type'], task['text'], task.get('msg'))
                if success: await increment_stat(task['lic_key'], task['source_id'], 'tg_sent_count', 1)
            elif task['action'] == 'album':
                success = await send_tg_album_with_retry(task['tgt'], task['downloaded_files'], task['text'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'tg_sent_count', 1)
            elif task['action'] == 'manual_single':
                success = await send_tg_manual_single_with_retry(task['uid'], task['file_path'], task['file_type'], task['text'], task['ch_title'], task['bot_api_from_chat_id'], task.get('msg'))
                if success: await increment_stat(task['lic_key'], task['source_id'], 'tg_sent_count', 1)
            elif task['action'] == 'manual_album':
                success = await send_tg_manual_album_with_retry(task['uid'], task['downloaded_files'], task['text'], task['ch_title'], task['bot_api_from_chat_id'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'tg_sent_count', 1)
        except Exception as e:
            LOGGER.error(f"❌ خطای TG Worker: {e}")
        finally:
            telegram_queue.task_done()
            await asyncio.sleep(2)  # ⏳ استراحت ۲ ثانیه‌ای تلگرام

async def bale_worker():
    while True:
        task = await bale_queue.get()
        try:
            if task['action'] == 'single':
                success = await send_to_bale(text=task['text'], file_path=task['file_path'], file_type=task['file_type'], filename=task['filename'], chat_id=task['tgt'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'bale_sent_count', 1)
            elif task['action'] == 'album':
                success = await send_album_to_bale(task['media_items'], chat_id=task['tgt'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'bale_sent_count', 1)
        except Exception as e:
            LOGGER.error(f"❌ خطای Bale Worker: {e}")
        finally:
            bale_queue.task_done()
            await asyncio.sleep(3)  # ⏳ استراحت ۳ ثانیه‌ای بله

async def eitaa_worker():
    while True:
        task = await eitaa_queue.get()
        try:
            if task['action'] == 'single':
                success = await send_to_eitaa(text=task['text'], file_path=task['file_path'], file_type=task['file_type'], filename=task['filename'], chat_id=task['tgt'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'eitaa_sent_count', 1)
            elif task['action'] == 'album':
                success = await send_album_to_eitaa(task['media_items'], chat_id=task['tgt'])
                if success: await increment_stat(task['lic_key'], task['source_id'], 'eitaa_sent_count', 1)
        except Exception as e:
            LOGGER.error(f"❌ خطای Eitaa Worker: {e}")
        finally:
            eitaa_queue.task_done()
            await asyncio.sleep(5)  # ⏳ استراحت ۵ ثانیه‌ای ایتا

async def periodic_temp_cleanup():
    # این تابع هر ۱ ساعت اجرا می‌شود و فایل‌های موقتی که بیش از ۱ ساعت از دانلودشان گذشته را پاک می‌کند
    while True:
        await asyncio.sleep(3600)
        try:
            now = time.time()
            count = 0
            for f in os.listdir(TEMP_DIR):
                f_path = os.path.join(TEMP_DIR, f)
                if os.path.isfile(f_path) and os.stat(f_path).st_mtime < now - 3600:
                    os.remove(f_path)
                    count += 1
            if count > 0:
                LOGGER.info(f"🧹 تعداد {count} فایل موقت قدیمی پاکسازی شد.")
        except Exception as e:
            LOGGER.error(f"خطا در پاکسازی Temp: {e}")
# =======================================================
# توابع پردازش جدید (سیستم Polling)
# =======================================================

async def process_single_message_task(msg, bot_api_from_chat_id, subscribers_licenses):
    for lic_key in subscribers_licenses:
        await increment_stat(lic_key, str(bot_api_from_chat_id), 'fetched_count', 1)

    clean_text = msg.text or ""
    unique_id, current_phash_str = await get_message_media_info(client, msg)
    
    file_path, file_type = None, None
    media_downloaded = False
    
    for lic_key in subscribers_licenses:
        mappings = await get_mappings(lic_key, str(bot_api_from_chat_id))
        if not mappings: continue
        
        forbidden_words = await get_forbidden_words(lic_key)
        is_forbidden = False
        if clean_text and forbidden_words:
            for fw in forbidden_words:
                if fw.lower() in clean_text.lower():
                    is_forbidden = True
                    break
        
        if is_forbidden:
            LOGGER.info(f"⛔️ مسدود شد (حاوی کلمه ممنوعه) | لایسنس {lic_key}")
            continue 
            
        clean_text_filtered = await apply_filters(clean_text, lic_key)
        norm_text_for_cache = normalize_text(clean_text_filtered)
        ch_title = await get_channel_title(lic_key, bot_api_from_chat_id)
        
        auto_targets = [m[0] for m in mappings if m[1] == 'auto']
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']
        
        for tgt in auto_targets:
            if await check_target_duplicate(lic_key, tgt, clean_text_filtered, unique_id, current_phash_str):
                LOGGER.info(f"🚫 مسدود شد (تکراری در تلگرام {tgt}) | '{get_preview(clean_text_filtered)}'")
                continue
            
            if msg.media and not DIRECT_COPY and not media_downloaded:
                try:
                    file_path = await client.download_media(msg, file=os.path.join(TEMP_DIR, f"single_{bot_api_from_chat_id}_{msg.id}"))
                    if msg.photo: file_type = 'photo'
                    elif msg.video: file_type = 'video'
                    elif msg.audio: file_type = 'audio'
                    elif msg.document: file_type = 'document'
                    media_downloaded = True
                except Exception as e:
                    LOGGER.error(f"❌ خطا در دانلود فایل تکی: {e}")

            # --- تلگرام ---
            target_info = await get_target_by_id(lic_key, tgt)
            if target_info:
                app_text = target_info[1]
                final_auto_text = f"{clean_text_filtered}\n\n{app_text}" if clean_text_filtered else app_text
                # 📥 قرار دادن در صف تلگرام
                await telegram_queue.put({'action': 'single', 'tgt': tgt, 'file_path': file_path, 'file_type': file_type, 'text': final_auto_text, 'msg': msg, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, str(tgt), unique_id, current_phash_str, norm_text_for_cache)

            # --- بله ---
            bale_targets = await get_bale_targets(lic_key)
            for bale_tgt, bale_app_text in bale_targets:
                if await check_target_duplicate(lic_key, f"bale_{bale_tgt}", clean_text_filtered, unique_id, current_phash_str): continue
                final_bale_text = f"{clean_text_filtered}\n\n{bale_app_text}" if clean_text_filtered else bale_app_text
                fname = msg.file.name if hasattr(msg, 'file') and msg.file else None
                # 📥 قرار دادن در صف بله
                await bale_queue.put({'action': 'single', 'tgt': bale_tgt, 'file_path': file_path, 'file_type': file_type, 'filename': fname, 'text': final_bale_text, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, f"bale_{bale_tgt}", unique_id, current_phash_str, norm_text_for_cache)
                    
            # --- ایتا ---
            eitaa_targets = await get_eitaa_targets(lic_key)
            for eitaa_tgt, eitaa_app_text in eitaa_targets:
                if await check_target_duplicate(lic_key, f"eitaa_{eitaa_tgt}", clean_text_filtered, unique_id, current_phash_str): continue
                final_eitaa_text = f"{clean_text_filtered}\n\n{eitaa_app_text}" if clean_text_filtered else eitaa_app_text
                fname = msg.file.name if hasattr(msg, 'file') and msg.file else None
                # 📥 قرار دادن در صف ایتا
                await eitaa_queue.put({'action': 'single', 'tgt': eitaa_tgt, 'file_path': file_path, 'file_type': file_type, 'filename': fname, 'text': final_eitaa_text, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, f"eitaa_{eitaa_tgt}", unique_id, current_phash_str, norm_text_for_cache)

        if manual_targets:
            if msg.media and not DIRECT_COPY and not media_downloaded:
                try:
                    file_path = await client.download_media(msg, file=os.path.join(TEMP_DIR, f"single_{bot_api_from_chat_id}_{msg.id}"))
                    if msg.photo: file_type = 'photo'
                    elif msg.video: file_type = 'video'
                    elif msg.audio: file_type = 'audio'
                    elif msg.document: file_type = 'document'
                    media_downloaded = True
                except Exception: pass
                
            users = await get_users_of_license(lic_key)
            for uid in users:
                await telegram_queue.put({'action': 'manual_single', 'uid': uid, 'file_path': file_path, 'file_type': file_type, 'text': clean_text_filtered, 'ch_title': ch_title, 'bot_api_from_chat_id': bot_api_from_chat_id, 'msg': msg, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
    
    return file_path
# =======================================================
# سیستم مدیریت هوشمند کش بر اساس کانال مقصد
# =======================================================

async def get_message_media_info(client, message):
    unique_id, current_phash_str = None, None
    if message and message.media:
        if hasattr(message.media, 'document') and message.media.document: unique_id = str(message.media.document.id)
        elif hasattr(message.media, 'photo') and message.media.photo: unique_id = str(message.media.photo.id)
        
        try:
            thumb_bytes = await client.download_media(message, file=bytes, thumb=-1)
            if thumb_bytes:
                current_phash_str = await asyncio.to_thread(calculate_phash, thumb_bytes)
        except Exception as e: 
            LOGGER.warning(f"⚠️ Could not generate thumbnail hash for media {unique_id}: {e}")
    return unique_id, current_phash_str

async def process_album_task(album_msgs, bot_api_from_chat_id, subscribers_licenses):
    for lic_key in subscribers_licenses:
        await increment_stat(lic_key, str(bot_api_from_chat_id), 'fetched_count', 1)

    caption = next((m.text for m in album_msgs if m.text), "")
    first_media_msg = next((m for m in album_msgs if m.media), album_msgs[0])
    unique_id, current_phash_str = await get_message_media_info(client, first_media_msg)

    downloaded_files = []
    media_downloaded = False
    
    for lic_key in subscribers_licenses:
        mappings = await get_mappings(lic_key, str(bot_api_from_chat_id))
        if not mappings: continue

        forbidden_words = await get_forbidden_words(lic_key)
        is_forbidden = False
        if caption and forbidden_words:
            for fw in forbidden_words:
                if fw.lower() in caption.lower():
                    is_forbidden = True
                    break
                    
        if is_forbidden:
            LOGGER.info(f"⛔️ مسدود شد آلبوم (حاوی کلمه ممنوعه) | لایسنس {lic_key}")
            continue 
            
        clean_caption = await apply_filters(caption, lic_key)
        norm_text_for_cache = normalize_text(clean_caption)
        ch_title = await get_channel_title(lic_key, bot_api_from_chat_id)
        
        auto_targets = [m[0] for m in mappings if m[1] == 'auto']
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']

        for tgt in auto_targets:
            if await check_target_duplicate(lic_key, str(tgt), clean_caption, unique_id, current_phash_str): continue

            if not DIRECT_COPY and not media_downloaded:
                for m in album_msgs:
                    try:
                        path = await client.download_media(m, file=os.path.join(TEMP_DIR, f"album_{bot_api_from_chat_id}_{m.grouped_id}_{m.id}"))
                        if path: downloaded_files.append({"msg": m, "path": path})
                    except Exception: pass
                media_downloaded = True
            
            if not downloaded_files and not DIRECT_COPY: continue

            # --- تلگرام ---
            target_info = await get_target_by_id(lic_key, tgt)
            if target_info:
                app_text = target_info[1]
                final_auto_caption = f"{clean_caption}\n\n{app_text}" if clean_caption else app_text
                await telegram_queue.put({'action': 'album', 'tgt': tgt, 'downloaded_files': downloaded_files, 'text': final_auto_caption, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, str(tgt), unique_id, current_phash_str, norm_text_for_cache)

            # --- بله ---
            bale_targets = await get_bale_targets(lic_key)
            for bale_tgt, bale_app_text in bale_targets:
                if await check_target_duplicate(lic_key, f"bale_{bale_tgt}", clean_caption, unique_id, current_phash_str): continue
                final_bale_caption = f"{clean_caption}\n\n{bale_app_text}" if clean_caption else bale_app_text
                bale_media_items = [{'type': 'photo' if item["msg"].photo else 'video', 'path': item["path"], 'caption': final_bale_caption if i == 0 else None} for i, item in enumerate(downloaded_files)]
                await bale_queue.put({'action': 'album', 'tgt': bale_tgt, 'media_items': bale_media_items, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, f"bale_{bale_tgt}", unique_id, current_phash_str, norm_text_for_cache)
                    
            # --- ایتا ---
            eitaa_targets = await get_eitaa_targets(lic_key)
            for eitaa_tgt, eitaa_app_text in eitaa_targets:
                if await check_target_duplicate(lic_key, f"eitaa_{eitaa_tgt}", clean_caption, unique_id, current_phash_str): continue
                final_eitaa_caption = f"{clean_caption}\n\n{eitaa_app_text}" if clean_caption else eitaa_app_text
                eitaa_media_items = [{'type': 'photo' if item["msg"].photo else 'video', 'path': item["path"], 'caption': final_eitaa_caption if i == 0 else None} for i, item in enumerate(downloaded_files)]
                await eitaa_queue.put({'action': 'album', 'tgt': eitaa_tgt, 'media_items': eitaa_media_items, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})
                await add_to_cache(lic_key, f"eitaa_{eitaa_tgt}", unique_id, current_phash_str, norm_text_for_cache)
        
        if manual_targets:
            if not DIRECT_COPY and not media_downloaded:
                for m in album_msgs:
                    try:
                        path = await client.download_media(m, file=os.path.join(TEMP_DIR, f"album_{bot_api_from_chat_id}_{m.grouped_id}_{m.id}"))
                        if path: downloaded_files.append({"msg": m, "path": path})
                    except Exception: pass
                media_downloaded = True
                
            if downloaded_files:
                users = await get_users_of_license(lic_key)
                for uid in users:
                    await telegram_queue.put({'action': 'manual_album', 'uid': uid, 'downloaded_files': downloaded_files, 'text': clean_caption, 'ch_title': ch_title, 'bot_api_from_chat_id': bot_api_from_chat_id, 'lic_key': lic_key, 'source_id': str(bot_api_from_chat_id)})

    return downloaded_files

async def process_unread_dialogs():
    from database import get_unique_source_channels
    try:
        channels = await get_unique_source_channels()
        if not channels: return

        target_ids = set()
        for ch in channels:
            ch_str = str(ch)
            if ch_str.startswith("-100"):
                target_ids.add(int(ch_str[4:]))
            target_ids.add(int(ch_str))
            
        dialogs = await client.get_dialogs(limit=100)
        
        for dialog in dialogs:
            dialog_id_str = str(dialog.id)
            bot_api_from_chat_id = dialog.id
            if not dialog_id_str.startswith("-100") and dialog.is_channel:
                bot_api_from_chat_id = int(f"-100{dialog.id}")
            
            if (dialog.id in target_ids or bot_api_from_chat_id in target_ids) and dialog.unread_count > 0:
                unread_count = dialog.unread_count
                entity = dialog.entity
                LOGGER.info(f"📥 {unread_count} پیام سین‌نخورده در کانال [{dialog.name}] یافت شد و در صف قرار گرفت.")
                
                fetch_limit = min(unread_count, 15)
                messages = await client.get_messages(entity, limit=fetch_limit)
                if not messages: continue
                    
                messages.reverse()
                
                subscribers_licenses = await get_license_subscribers(bot_api_from_chat_id)
                if not subscribers_licenses:
                    LOGGER.info(f"⚠️ کانال [{dialog.name}] هیچ لایسنس فعالی ندارد. فقط سین زده می‌شود.")
                    await client.send_read_acknowledge(entity)
                    continue

                albums_dict = {}
                singles = []
                
                for msg in messages:
                    if msg.grouped_id:
                        if msg.grouped_id not in albums_dict:
                            albums_dict[msg.grouped_id] = []
                        albums_dict[msg.grouped_id].append(msg)
                    else:
                        singles.append(msg)
                
                # فقط پیام‌ها را فیلتر کرده و در صف‌ها می‌اندازیم
                for grp_id, album_msgs in albums_dict.items():
                    await process_album_task(album_msgs, bot_api_from_chat_id, subscribers_licenses)
                    
                for msg in singles:
                    await process_single_message_task(msg, bot_api_from_chat_id, subscribers_licenses)
                
                await client.send_read_acknowledge(entity)
                
    except Exception as e:
        LOGGER.error(f"❌ خطا در پردازش گفتگوهای سین‌نخورده: {e}")
        
async def main():
    asyncio.create_task(periodic_cache_cleanup())
    asyncio.create_task(periodic_temp_cleanup())
    
    asyncio.create_task(telegram_worker())
    asyncio.create_task(bale_worker())
    asyncio.create_task(eitaa_worker())
        
    try:
        LOGGER.info("⏳ Checking the connection of the account to the server...")
        await client.start(phone_number)
        me_client = await client.get_me()      
        LOGGER.info(f"✅ Ping OK: Account connected to server (Name: {me_client.first_name})")
    except Exception as e:
        LOGGER.error(f"❌ Account connection failed! Check proxy. Error: {e}")
        return 

    # 🚀 باز کردن و آماده‌سازی سلنیوم ایتا در ابتدای اجرای ربات 
    try:
        LOGGER.info("🌐 [Eitaa] در حال راه‌اندازی مرورگر ایتا در پس‌زمینه... (این کار ممکن است چند ثانیه طول بکشد)")
        # اجرای سلنیوم در ترد مجزا تا روند اصلی متوقف نشود
        await asyncio.to_thread(get_eitaa_driver) 
    except Exception as e:
        LOGGER.error(f"❌ [Eitaa] خطا در راه‌اندازی اولیه مرورگر ایتا: {e}")

    async def polling_loop():
        LOGGER.info("🔄 سیستم هوشمند بررسی دوره‌ای پیام‌های سین‌نخورده فعال شد...")
        while True:
            try:
                await asyncio.wait_for(process_unread_dialogs(), timeout=600.0)
                
            except asyncio.TimeoutError:
                LOGGER.warning("⚠️ عملیات بررسی بیش از حد طول کشید (احتمالاً به دلیل کندی شبکه). لغو و شروع مجدد...")
            except Exception as e:
                LOGGER.error(f"❌ خطای کلی در چرخه چرخشی (Polling): {e}")
                
            await asyncio.sleep(10)

    # اجرای حلقه بی‌پایان در پس‌زمینه
    asyncio.create_task(polling_loop())
    
    # نگه داشتن سشن برای جلوگیری از قطع اتصال
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())