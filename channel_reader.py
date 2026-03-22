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
from database import get_subscribers, get_remove_words, get_channel_title, ALBUM_CAPTIONS, get_mappings, get_target_by_id, get_bale_targets
import sys
import json
import re
import time
import io
from PIL import Image
import imagehash
from thefuzz import fuzz
from database import init_cache_table, add_to_cache, get_recent_cache, cleanup_cache
from bale_sender import send_to_bale, send_album_to_bale
from database import increment_stat
from eitaa_sender import send_to_eitaa, send_album_to_eitaa

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
            return
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Album Timeout for {tgt} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: LOGGER.error(f"❌ Failed to send album to {tgt}.")
            else: await asyncio.sleep(3)
        finally:
            for f in opened_files: f.close()

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
            return
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Manual Album Error for {user_id} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: LOGGER.error(f"❌ Failed manual album to {user_id}.")
            else: await asyncio.sleep(3)
        finally:
            for f in opened_files: f.close()

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
            return
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Single Timeout for {tgt} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: LOGGER.error(f"❌ Failed single msg to {tgt}.")
            else: await asyncio.sleep(3)

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
            return
        except Exception as e:
            LOGGER.warning(f"⚠️ TG Manual Single Error for {user_id} (Attempt {attempt+1}/3): {e}")
            if attempt == 2: LOGGER.error(f"❌ Failed manual single msg to {user_id}.")
            else: await asyncio.sleep(3)

# =======================================================
# توابع فیلترینگ و اجرای اصلی برنامه
# =======================================================

async def apply_filters(text: str, user_id: int):
    if not text: return text
    
    text = re.sub(r'\(?https?://\S+\)?', '', text)
    
    bad_words = await get_remove_words(user_id)
    bad_words.sort(key=len, reverse=True)
    for word in bad_words:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        text = pattern.sub("", text)
    
    text = re.sub(r'[ \t]+', ' ', text)
    
    text = re.sub(r'(?:[^\w.!?،؛)\]"\'»]|\s)+$', '', text)
    
    text = text.strip()
    
    return text

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

async def check_and_cache_duplicate(client, message, text_to_check: str) -> bool:
    norm_text = normalize_text(text_to_check)
    recent_posts = await get_recent_cache()
    preview_new = get_preview(text_to_check)
    
    if norm_text and len(norm_text) > 15:
        for _, _, cached_text in recent_posts:
            if cached_text and len(cached_text) > 15:
                if fuzz.ratio(norm_text, cached_text) >= 60: 
                    preview_old = get_preview(cached_text)
                    LOGGER.info(f"🚫 مسدود شد (متن تکراری) | جدید: '{preview_new}' | کش‌شده: '{preview_old}'")
                    return True 

    unique_id, current_phash_str = None, None
    if message.media:
        if hasattr(message.media, 'document') and message.media.document: unique_id = str(message.media.document.id)
        elif hasattr(message.media, 'photo') and message.media.photo: unique_id = str(message.media.photo.id)
            
        if unique_id:
            for cached_uid, _, _ in recent_posts:
                if cached_uid == unique_id: 
                    LOGGER.info(f"🚫 مسدود شد (فایل دقیقاً مشابه) | '{preview_new}'")
                    return True
        try:
            thumb_bytes = await client.download_media(message, file=bytes, thumb=-1)
            if thumb_bytes:
                current_phash_str = await asyncio.to_thread(calculate_phash, thumb_bytes)
                current_phash = imagehash.hex_to_hash(current_phash_str)
                
                for _, cached_phash, _ in recent_posts:
                    if cached_phash:
                        cached_hash_obj = imagehash.hex_to_hash(cached_phash)
                        if current_phash - cached_hash_obj <= 5: 
                            LOGGER.info(f"🚫 مسدود شد (تصویر مشابه) | '{preview_new}'")
                            return True 
        except Exception: pass
            
    await add_to_cache(unique_id, current_phash_str, norm_text)
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
# توابع پردازش جدید (سیستم Polling)
# =======================================================

async def process_single_message_task(msg, bot_api_from_chat_id, subscribers, all_send_tasks):
    for uid in subscribers:
        await increment_stat(uid, str(bot_api_from_chat_id), 'fetched_count', 1)

    clean_text = msg.text or ""
    unique_id, current_phash_str = await get_message_media_info(client, msg)
    
    file_path, file_type = None, None
    media_downloaded = False
    
    for user_id in subscribers:
        mappings = await get_mappings(user_id, str(bot_api_from_chat_id))
        if not mappings: continue
            
        # ۱. فیلتر کلمات حذفی بر اساس تنظیمات این کاربر خاص
        clean_text_filtered = await apply_filters(clean_text, user_id)
        norm_text_for_cache = normalize_text(clean_text_filtered)
        ch_title = await get_channel_title(user_id, bot_api_from_chat_id)
        
        auto_targets = [m[0] for m in mappings if m[1] == 'auto']
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']
        
        for tgt in auto_targets:
            # ۲. بررسی تکراری بودن روی متن فیلتر شده و منحصراً برای همین کانال مقصد
            if await check_target_duplicate(tgt, clean_text_filtered, unique_id, current_phash_str):
                LOGGER.info(f"🚫 مسدود شد (تکراری در کانال مقصد {tgt}) | '{get_preview(clean_text_filtered)}'")
                continue
            
            # ۳. دانلود مدیا فقط در صورتی که حداقل یک کانال مقصد به آن نیاز داشته باشد
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

            target_info = await get_target_by_id(user_id, tgt)
            if not target_info: continue
            app_text = target_info[1]
            final_auto_text = f"{clean_text_filtered}\n\n{app_text}" if clean_text_filtered else app_text
            
            all_send_tasks.append(track_task(send_tg_single_with_retry(tgt, file_path, file_type, final_auto_text, msg), user_id, str(bot_api_from_chat_id), 'tg_sent_count'))
            
            # ۴. ثبت در کش اختصاصی همین مقصد
            await add_to_cache(str(tgt), unique_id, current_phash_str, norm_text_for_cache)

            # --- ارسال به مقصدهای بله ---
            if auto_targets: # فقط در صورتی که این مبدأ برای کاربر فعال باشد
                bale_targets = await get_bale_targets(user_id)
                for bale_tgt, bale_app_text in bale_targets:
                    # استفاده از کلید کش متفاوت (پیشوند bale_) تا با تلگرام تداخل نکند
                    if await check_target_duplicate(f"bale_{bale_tgt}", clean_text_filtered, unique_id, current_phash_str):
                        LOGGER.info(f"🚫 مسدود شد (تکراری در بله {bale_tgt}) | '{get_preview(clean_text_filtered)}'")
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
                            LOGGER.error(f"❌ خطا در دانلود فایل تکی برای بله: {e}")
    
                    final_bale_text = f"{clean_text_filtered}\n\n{bale_app_text}" if clean_text_filtered else bale_app_text
                    fname = msg.file.name if hasattr(msg, 'file') and msg.file else None
                    
                    all_send_tasks.append(track_task(send_to_bale(text=final_bale_text, file_path=file_path, file_type=file_type, filename=fname, chat_id=bale_tgt), user_id, str(bot_api_from_chat_id), 'bale_sent_count'))
                    
                    await add_to_cache(f"bale_{bale_tgt}", unique_id, current_phash_str, norm_text_for_cache)
            # if not eitaa_sent:
            #     fname = msg.file.name if hasattr(msg, 'file') and msg.file else None
            #     all_send_tasks.append(track_task(send_to_eitaa(text=final_auto_text, file_path=file_path, file_type=file_type, filename=fname), user_id, str(bot_api_from_chat_id), 'eitaa_sent_count'))
            #     eitaa_sent = True

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
                
            all_send_tasks.append(track_task(send_tg_manual_single_with_retry(user_id, file_path, file_type, clean_text_filtered, ch_title, bot_api_from_chat_id, msg), user_id, str(bot_api_from_chat_id), 'tg_sent_count'))
    
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
        except Exception: pass
    return unique_id, current_phash_str

async def check_target_duplicate(target_id: str, filtered_text: str, unique_id: str, current_phash_str: str) -> bool:
    norm_text = normalize_text(filtered_text)
    recent_posts = await get_recent_cache(str(target_id))
    
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

async def process_album_task(album_msgs, bot_api_from_chat_id, subscribers, all_send_tasks):
    for uid in subscribers:
        await increment_stat(uid, str(bot_api_from_chat_id), 'fetched_count', 1)

    caption = next((m.text for m in album_msgs if m.text), "")
    first_media_msg = next((m for m in album_msgs if m.media), album_msgs[0])
    unique_id, current_phash_str = await get_message_media_info(client, first_media_msg)

    downloaded_files = []
    media_downloaded = False
    
    for user_id in subscribers:
        mappings = await get_mappings(user_id, str(bot_api_from_chat_id))
        if not mappings: continue
            
        clean_caption = await apply_filters(caption, user_id)
        norm_text_for_cache = normalize_text(clean_caption)
        ch_title = await get_channel_title(user_id, bot_api_from_chat_id)
        
        auto_targets = [m[0] for m in mappings if m[1] == 'auto']
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']

        for tgt in auto_targets:
            # بررسی تکراری بودن روی کپشن فیلتر شده و برای همین کانال مقصد
            if await check_target_duplicate(tgt, clean_caption, unique_id, current_phash_str):
                LOGGER.info(f"🚫 مسدود شد آلبوم (تکراری در کانال مقصد {tgt}) | '{get_preview(clean_caption)}'")
                continue

            # دانلود مدیاها در صورت نیاز
            if not DIRECT_COPY and not media_downloaded:
                for m in album_msgs:
                    try:
                        path = await client.download_media(m, file=os.path.join(TEMP_DIR, f"album_{bot_api_from_chat_id}_{m.grouped_id}_{m.id}"))
                        if path: downloaded_files.append({"msg": m, "path": path})
                    except Exception as e:
                        LOGGER.error(f"❌ خطا در دانلود دیتای آلبوم: {e}")
                media_downloaded = True
            
            if not downloaded_files and not DIRECT_COPY: continue

            target_info = await get_target_by_id(user_id, tgt)
            if not target_info: continue
            app_text = target_info[1]
            final_auto_caption = f"{clean_caption}\n\n{app_text}" if clean_caption else app_text
            
            all_send_tasks.append(track_task(send_tg_album_with_retry(tgt, downloaded_files, final_auto_caption), user_id, str(bot_api_from_chat_id), 'tg_sent_count'))
            await add_to_cache(str(tgt), unique_id, current_phash_str, norm_text_for_cache)

            # --- ارسال به مقصدهای بله ---
            if auto_targets:
                bale_targets = await get_bale_targets(user_id)
                for bale_tgt, bale_app_text in bale_targets:
                    if await check_target_duplicate(f"bale_{bale_tgt}", clean_caption, unique_id, current_phash_str):
                        LOGGER.info(f"🚫 مسدود شد آلبوم (تکراری در بله {bale_tgt}) | '{get_preview(clean_caption)}'")
                        continue
                    
                    if not DIRECT_COPY and not media_downloaded:
                        for m in album_msgs:
                            try:
                                path = await client.download_media(m, file=os.path.join(TEMP_DIR, f"album_{bot_api_from_chat_id}_{m.grouped_id}_{m.id}"))
                                if path: downloaded_files.append({"msg": m, "path": path})
                            except Exception as e:
                                LOGGER.error(f"❌ خطا در دانلود دیتای آلبوم بله: {e}")
                        media_downloaded = True
                    
                    if not downloaded_files and not DIRECT_COPY: continue
    
                    final_bale_caption = f"{clean_caption}\n\n{bale_app_text}" if clean_caption else bale_app_text
                    bale_media_items = [{'type': 'photo' if item["msg"].photo else 'video', 'path': item["path"], 'caption': final_bale_caption if i == 0 else None} for i, item in enumerate(downloaded_files)]
                    
                    all_send_tasks.append(track_task(send_album_to_bale(bale_media_items, chat_id=bale_tgt), user_id, str(bot_api_from_chat_id), 'bale_sent_count'))
                    
                    await add_to_cache(f"bale_{bale_tgt}", unique_id, current_phash_str, norm_text_for_cache)
            # if not eitaa_sent:
            #     eitaa_media_items = [{'path': item["path"], 'caption': final_auto_caption if i == 0 else None} for i, item in enumerate(downloaded_files)]
            #     all_send_tasks.append(track_task(send_album_to_eitaa(eitaa_media_items), user_id, str(bot_api_from_chat_id), 'eitaa_sent_count'))
            #     eitaa_sent = True
        
        if manual_targets:
            if not DIRECT_COPY and not media_downloaded:
                for m in album_msgs:
                    try:
                        path = await client.download_media(m, file=os.path.join(TEMP_DIR, f"album_{bot_api_from_chat_id}_{m.grouped_id}_{m.id}"))
                        if path: downloaded_files.append({"msg": m, "path": path})
                    except Exception: pass
                media_downloaded = True
                
            if downloaded_files:
                all_send_tasks.append(track_task(send_tg_manual_album_with_retry(user_id, downloaded_files, clean_caption, ch_title, bot_api_from_chat_id), user_id, str(bot_api_from_chat_id), 'tg_sent_count'))

    return downloaded_files

async def process_unread_dialogs():
    from database import get_unique_source_channels
    
    try:
        channels = await get_unique_source_channels()
        if not channels:
            return

        # استانداردسازی آیدی‌ها برای جستجوی دقیق‌تر
        target_ids = set()
        for ch in channels:
            ch_str = str(ch)
            if ch_str.startswith("-100"):
                target_ids.add(int(ch_str[4:])) # آیدی بدون -100 (برای تطابق با برخی خروجی‌های تلتون)
            target_ids.add(int(ch_str))
            
        dialogs = await client.get_dialogs(limit=100)
        
        for dialog in dialogs:
            # همگام‌سازی آیدی دیالوگ با فرمت بات ای‌پی‌آی
            dialog_id_str = str(dialog.id)
            bot_api_from_chat_id = dialog.id
            if not dialog_id_str.startswith("-100") and dialog.is_channel:
                bot_api_from_chat_id = int(f"-100{dialog.id}")
            
            # بررسی اینکه آیا دیالوگ هدف ماست و آیا پیام خوانده‌نشده دارد؟
            if (dialog.id in target_ids or bot_api_from_chat_id in target_ids) and dialog.unread_count > 0:
                unread_count = dialog.unread_count
                entity = dialog.entity
                LOGGER.info(f"📥 {unread_count} پیام سین‌نخورده در کانال [{dialog.name}] یافت شد.")
                
                # دریافت پیام‌های خوانده‌نشده
                fetch_limit = min(unread_count, 15)
                messages = await client.get_messages(entity, limit=fetch_limit)
                if not messages:
                    continue
                    
                messages.reverse() # از قدیمی‌ترین به جدیدترین برای حفظ ترتیب فوروارد
                
                subscribers = await get_subscribers(bot_api_from_chat_id)
                if not subscribers:
                    LOGGER.info(f"⚠️ کانال [{dialog.name}] هیچ مشترکی ندارد. فقط سین زده می‌شود.")
                    await client.send_read_acknowledge(entity)
                    continue

                albums_dict = {}
                singles = []
                
                # تفکیک آلبوم‌ها از پیام‌های تکی
                for msg in messages:
                    if msg.grouped_id:
                        if msg.grouped_id not in albums_dict:
                            albums_dict[msg.grouped_id] = []
                        albums_dict[msg.grouped_id].append(msg)
                    else:
                        singles.append(msg)

                all_send_tasks = []
                files_to_remove = []
                
                # --- پردازش آلبوم‌ها ---
                for grp_id, album_msgs in albums_dict.items():
                    dl_files = await process_album_task(album_msgs, bot_api_from_chat_id, subscribers, all_send_tasks)
                    files_to_remove.extend([f["path"] for f in dl_files])
                    
                # --- پردازش پیام‌های تکی ---
                for msg in singles:
                    f_path = await process_single_message_task(msg, bot_api_from_chat_id, subscribers, all_send_tasks)
                    if f_path: files_to_remove.append(f_path)
                    
                # اجرای تمام ارسال‌ها به صورت کاملا موازی
                if all_send_tasks:
                    LOGGER.info(f"⏳ در حال ارسال {len(all_send_tasks)} تسک به مقصدهای تعیین‌شده...")
                    await asyncio.gather(*all_send_tasks)
                    
                # پاکسازی فایل‌های سیستم
                for path in files_to_remove:
                    await safe_remove_file(path)
                
                # سین زدن (ثبت وضعیت خوانده شده)
                await client.send_read_acknowledge(entity)
                LOGGER.info(f"✅ تمام پیام‌های جدید کانال [{dialog.name}] با موفقیت پردازش و سین خوردند.")
                
    except Exception as e:
        LOGGER.error(f"❌ خطا در پردازش گفتگوهای سین‌نخورده: {e}")

async def main():
    await init_cache_table()
    asyncio.create_task(periodic_cache_cleanup())
    
    try:
        LOGGER.info("⏳ Checking the connection of the account to the server...")
        await client.start(phone_number)
        me_client = await client.get_me()      
        LOGGER.info(f"✅ Ping OK: Account connected to server (Name: {me_client.first_name})")
    except Exception as e:
        LOGGER.error(f"❌ Account connection failed! Check proxy. Error: {e}")
        return 

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