import os
import sys
import logging
import asyncio
import time
from dotenv import load_dotenv

# 💡 ایمپورت‌های سلنیوم به بالای فایل منتقل شدند تا پایتون گیج نشود
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

load_dotenv(resource_path(".env"))
channel = os.getenv("eitaa_channel", "").strip()
LOGGER = logging.getLogger(__name__)

# --- متغیرهای وب ---
driver = None
is_browser_open = False

def get_driver():
    global driver, is_browser_open
    if not is_browser_open:
        try:
            options = webdriver.ChromeOptions()
            profile_path = os.path.join(os.path.abspath("."), "eitaa_profile")
            options.add_argument(f"user-data-dir={profile_path}")
            
            LOGGER.info("🌐 در حال باز کردن مرورگر ایتا وب...")
            # اجرای اتوماتیک کروم
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.get("https://web.eitaa.com/")
            is_browser_open = True
            
            time.sleep(5)
            LOGGER.info("⚠️ هشدار: یک مرورگر کروم باز شد. اگر در ایتا لاگین نیستید، لطفاً سریعاً شماره خود را وارد کرده و لاگین کنید.")
        except Exception as e:
            LOGGER.error(f"❌ خطا در باز کردن مرورگر: {e}")
    return driver

def send_message_via_web(text, file_path, chat_id):
    br = get_driver()
    if not br: return False

    try:
        # ۱. باز کردن مستقیم چتِ کانال مقصد
        chat_id = chat_id.replace("@", "")
        br.get(f"https://web.eitaa.com/#/im?p=@{chat_id}")
        time.sleep(5) # صبر برای لود شدن کامل چت

        if file_path:
            # ۲. پیدا کردن دکمه مخفی آپلود فایل و ارسال مسیر فایل
            file_input = br.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(os.path.abspath(file_path))
            time.sleep(3) # صبر برای لود شدن پنجره پیش‌نمایش
            
            # ۳. نوشتن کپشن زیر عکس (در صورت وجود)
            if text:
                text_boxes = br.find_elements(By.CSS_SELECTOR, ".composer_rich_textarea")
                if len(text_boxes) > 1:
                    text_boxes[-1].send_keys(text)
                elif len(text_boxes) == 1:
                    text_boxes[0].send_keys(text)
                time.sleep(1)
            
            # ۴. زدن دکمه ارسال (اینتر)
            body = br.find_element(By.CSS_SELECTOR, "body")
            body.send_keys(Keys.CONTROL, Keys.RETURN)
            time.sleep(2)
            
            # اگر شورت‌کات کار نکرد، کلیک روی دکمه ارسال
            try:
                send_btn = br.find_element(By.CSS_SELECTOR, "button.btn-primary")
                send_btn.click()
                time.sleep(2)
            except: pass
            
        else:
            # ارسال متن خالی
            input_box = WebDriverWait(br, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".composer_rich_textarea"))
            )
            input_box.send_keys(text)
            time.sleep(1)
            input_box.send_keys(Keys.RETURN)
            time.sleep(2)

        return True
    except Exception as e:
        LOGGER.error(f"❌ خطا در رباتِ ایتا وب: {e}")
        return False

async def send_to_eitaa(text: str = None, file_path: str = None, file_type: str = None, filename: str = None, chat_id: str = channel):
    if not chat_id: return False
    
    success = await asyncio.to_thread(send_message_via_web, text, file_path, chat_id)
    if success:
        LOGGER.info(f"✅ ({chat_id}) پیام از طریق مرورگرِ ایتا وب ارسال شد!")
    return success

async def send_album_to_eitaa(media_items: list, chat_id: str = channel):
    success = True
    for idx, item in enumerate(media_items):
        file_path = item['path']
        caption = item.get('caption') if idx == 0 else None
        result = await send_to_eitaa(text=caption, file_path=file_path, chat_id=chat_id)
        if not result: success = False
    return success