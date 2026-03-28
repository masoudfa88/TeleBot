import os
import sys
import httpx
import logging
from dotenv import load_dotenv
import json
import asyncio

def get_preview(text, n=4):
    if not text: return "[بدون متن]"
    words = str(text).split()
    return " ".join(words[:n]) + ("..." if len(words) > n else "")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

load_dotenv(resource_path(".env"))

BALE_TOKEN = os.getenv("BALE_BOT_TOKEN")
# channel = os.getenv("cannel")
BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_TOKEN}"
LOGGER = logging.getLogger(__name__)

async def send_to_bale(text: str = None, file_path: str = None, file_type: str = None, filename: str = None, chat_id: str = None):
    if not BALE_TOKEN or not chat_id:
        return False

    timeout_settings = httpx.Timeout(45.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout_settings) as client:
        try:
            if not file_path:
                payload = {"chat_id": chat_id, "text": text or ""}
                for attempt in range(3):
                    try:
                        response = await client.post(f"{BALE_API_URL}/sendMessage", json=payload)
                        response.raise_for_status()
                        break
                    except Exception as e:
                        if attempt == 2: raise e
                        await asyncio.sleep(2)
            else:
                data = {"chat_id": chat_id}
                if text: data["caption"] = text
                
                if file_type == 'photo':
                    endpoint, mime, param_name, default_name = "sendPhoto", "image/jpeg", "photo", "image.jpg"
                elif file_type == 'video':
                    endpoint, mime, param_name, default_name = "sendVideo", "video/mp4", "video", "video.mp4"
                elif file_type == 'audio':
                    endpoint, mime, param_name, default_name = "sendAudio", "audio/mpeg", "audio", "audio.mp3"
                elif file_type == 'document':
                    endpoint, mime, param_name, default_name = "sendDocument", "application/octet-stream", "document", filename or "document.file"
                else:
                    return

                # باز کردن فایل در داخل حلقه قرار گرفت تا در صورت خطا از ابتدا خوانده شود
                for attempt in range(3):
                    try:
                        with open(file_path, 'rb') as f:
                            files = {param_name: (default_name, f, mime)}
                            response = await client.post(f"{BALE_API_URL}/{endpoint}", data=data, files=files)
                            response.raise_for_status()
                        break
                    except Exception as e:
                        if attempt == 2: raise e
                        await asyncio.sleep(2)
            
            preview = get_preview(text)                
            LOGGER.info(f"✅ ({chat_id}) Sent to BALE: '{preview}'")
            return True
        except Exception as e:
            LOGGER.error(f"❌ Failed To send BALE: {e}")
            return False
            
async def send_album_to_bale(media_items: list, chat_id: str = None):
    if not BALE_TOKEN or not chat_id:
        return False

    url = f"{BALE_API_URL}/sendMediaGroup"
    timeout_settings = httpx.Timeout(90.0, connect=15.0)
    
    async with httpx.AsyncClient(timeout=timeout_settings) as client:
        for attempt in range(3):
            opened_files = []
            files = {}
            media_json = []
            try:
                for idx, item in enumerate(media_items):
                    file_type, file_path, caption = item['type'], item['path'], item.get('caption')
                    attach_name = f"file{idx}"
                    
                    media_obj = {"type": file_type, "media": f"attach://{attach_name}"}
                    if caption: media_obj["caption"] = caption
                    media_json.append(media_obj)
                    
                    mime = "image/jpeg" if file_type == "photo" else "video/mp4"
                    filename = f"{attach_name}.jpg" if file_type == "photo" else f"{attach_name}.mp4"
                    
                    # فایل در هر بار تلاش دوباره و از ابتدا باز میشود
                    f = open(file_path, 'rb')
                    opened_files.append(f)
                    files[attach_name] = (filename, f, mime)
                    
                data = {"chat_id": chat_id, "media": json.dumps(media_json)}
                response = await client.post(url, data=data, files=files)
                response.raise_for_status()
                first_caption = next((item.get('caption') for item in media_items if item.get('caption')), "")
                preview = get_preview(first_caption)
                LOGGER.info(f"✅ آلبوم با موفقیت به بله ({chat_id}) ارسال شد: '{preview}'")
                return True
                break # موفقیت و خروج از حلقه Retry
            except Exception as e:
                if attempt == 2: 
                    LOGGER.error(f"❌ خطا در ارسال آلبوم به بله: {e}")
                    return False
                else:
                    await asyncio.sleep(2)
            finally:
                for f in opened_files:
                    f.close()