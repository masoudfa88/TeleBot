import os
import sys
import logging
import asyncio
import time
import uuid
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

load_dotenv(resource_path(".env"))
LOGGER = logging.getLogger(__name__)

driver = None
is_browser_open = False
upload_counter = 0

def get_driver():
    global driver, is_browser_open
    if not is_browser_open:
        try:
            options = webdriver.ChromeOptions()
            profile_path = os.path.join(os.path.abspath("."), "eitaa_server_profile")
            options.add_argument(f"user-data-dir={profile_path}")
            
            # options.add_argument("--headless=new") 
            
            options.add_argument("--window-size=1920,1080") 
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-software-rasterizer")
            options.add_argument("--disable-extensions")
            
            LOGGER.info("🌐 [Eitaa] Starting Chrome Driver (Headless)...")
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            driver.get("https://web.eitaa.com/")
            
            LOGGER.info("⏳ [Eitaa] Waiting for Eitaa to load...")
            WebDriverWait(driver, 120).until(EC.presence_of_element_located((By.ID, "main-search")))
            LOGGER.info("✅ [Eitaa] Eitaa Web Loaded Successfully!")
            is_browser_open = True
        except Exception as e:
            LOGGER.error(f"❌ [Eitaa] Error starting browser: {e}")
    return driver

def verify_upload(br, tag_name, timeout_seconds):
    success = False
    for _ in range(timeout_seconds):
        try:
            new_msgs = br.find_elements(By.CSS_SELECTOR, f".message:not([{tag_name}='true']), .bubble:not([{tag_name}='true'])")
            if len(new_msgs) > 0:
                last_msg = new_msgs[-1]
                success_icons = last_msg.find_elements(By.CSS_SELECTOR, ".tgico-channelviews, .tgico-check, .tgico-checks, .message-views, i[class*='view'], span[class*='view']")
                loading_icons = last_msg.find_elements(By.CSS_SELECTOR, ".tgico-time, .progress, .spinner, .loading")
                
                if len(success_icons) > 0 and len(loading_icons) == 0:
                    success = True
                    break
        except Exception as e: 
            LOGGER.debug(f"⚠️ [Eitaa] Verification loop exception: {e}")
        time.sleep(1)
    return success

def send_media(br, file_paths_list, caption_text, tag_name, timeout=120):
    LOGGER.info(f"🏷️ [Eitaa] Tagging old messages ({tag_name})...")
    br.execute_script(f"document.querySelectorAll('.message, .bubble').forEach(el => el.setAttribute('{tag_name}', 'true'));")

    attach_btn = WebDriverWait(br, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".attach-file")))
    attach_btn.click()
    time.sleep(1)

    LOGGER.info(f"⚙️ [Eitaa] Uploading {len(file_paths_list)} files to browser input...")
    file_input = br.find_element(By.CSS_SELECTOR, "input[type='file']")
    br.execute_script("arguments[0].setAttribute('accept', '*/*');", file_input)
    
    paths_string = "\n".join(file_paths_list)
    file_input.send_keys(paths_string)
    
    WebDriverWait(br, 15).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "div[contenteditable='true']")) >= 2)
    
    try:
        for label in br.find_elements(By.XPATH, "//label[contains(., 'فشرده')]"):
            cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            if not cb.is_selected(): br.execute_script("arguments[0].click();", cb)
        for label in br.find_elements(By.XPATH, "//label[contains(., 'فایل')]"):
            cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            if cb.is_selected(): br.execute_script("arguments[0].click();", cb)
    except Exception as e: 
        LOGGER.warning(f"⚠️ [Eitaa] Could not handle compression checkboxes: {e}")

    caption_box = br.find_elements(By.CSS_SELECTOR, "div[contenteditable='true']")[-1] 
    
    if caption_text:
        # تغییر مهم برای تزریق فرمت بولد در ایتا
        html_caption = caption_text.replace('\n', '<br>')
        br.execute_script("arguments[0].focus(); document.execCommand('insertHTML', false, arguments[1]);", caption_box, html_caption)
        
    caption_box.send_keys(" ")
    time.sleep(1)
    
    LOGGER.info("🚀 [Eitaa] Sending media...")
    caption_box.send_keys(Keys.RETURN)
    time.sleep(1)
    ActionChains(br).send_keys(Keys.RETURN).perform()
    
    try: WebDriverWait(br, 10).until(EC.staleness_of(caption_box))
    except Exception as e: 
        LOGGER.warning(f"⚠️ [Eitaa] Popup did not close within 10s: {e}")

    if verify_upload(br, tag_name, timeout):
        LOGGER.info("🎉 [Eitaa] Upload Confirmed! ✅")
        return True
    else:
        LOGGER.warning("⚠️ [Eitaa] Upload confirmation timeout (file might still be uploading).")
        return False

def send_text(br, text_message, tag_name, timeout=30):
    LOGGER.info(f"🏷️ [Eitaa] Tagging old messages ({tag_name})...")
    br.execute_script(f"document.querySelectorAll('.message, .bubble').forEach(el => el.setAttribute('{tag_name}', 'true'));")

    LOGGER.info("✍️ [Eitaa] Locating chat box...")
    chat_box = WebDriverWait(br, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.input-message-input:not(.input-field-input-fake)"))
    )
    
    try: chat_box.click() 
    except Exception as e: 
        LOGGER.debug(f"⚠️ [Eitaa] Standard click failed, using JS click: {e}")
        br.execute_script("arguments[0].click();", chat_box)
    time.sleep(1)

    LOGGER.info("✍️ [Eitaa] Injecting text and sending input signal...")
    js_script = """
        var box = arguments[0]; box.focus();
        document.execCommand('insertHTML', false, arguments[1]);
        box.dispatchEvent(new Event('input', { bubbles: true }));
    """
    html_text = text_message.replace('\n', '<br>')
    br.execute_script(js_script, chat_box, html_text)
    chat_box.send_keys(" ") 
    time.sleep(1)
    
    LOGGER.info("🚀 [Eitaa] Sending text...")
    chat_box.send_keys(Keys.RETURN)
    time.sleep(1)
    ActionChains(br).send_keys(Keys.RETURN).perform()

    if verify_upload(br, tag_name, timeout):
        LOGGER.info("🎉 [Eitaa] Text Message Sent! ✅")
        return True
    else:
        LOGGER.warning("⚠️ [Eitaa] Text message sent but no server confirmation received.")
        return False
def process_eitaa_message(text, file_paths, chat_id):
    global upload_counter
    br = get_driver()
    if not br: return False
    
    try:
        if file_paths:
            if upload_counter >= 5:
                LOGGER.info("🔄 [Eitaa] Reached 5 uploads limit. Refreshing page to clear browser memory...")
                try:
                    br.get("https://web.eitaa.com/")
                    time.sleep(5)
                    WebDriverWait(br, 30).until(EC.presence_of_element_located((By.ID, "main-search")))
                    LOGGER.info("✅ [Eitaa] Page refreshed successfully.")
                except Exception as e:
                    LOGGER.warning(f"⚠️ [Eitaa] Refresh timeout/error, continuing anyway: {e}")
                
                upload_counter = 0 # ریست شمارشگر
            
            upload_counter += 1 # افزودن به شمارشگر آپلود

        chat_id = chat_id.replace("@", "").replace("https://eitaa.com/", "").strip()
        LOGGER.info(f"🔄 [Eitaa] Switching channel to @{chat_id} ...")
        
        br.get(f"https://web.eitaa.com/#/im?p=@{chat_id}")
        
        time.sleep(2)
        LOGGER.info(f"🔄 [Eitaa] Refreshing the page for @{chat_id} to prevent race conditions...")
        br.refresh()
        time.sleep(2)
        
        try:
            WebDriverWait(br, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".attach-file")))
        except Exception:
            LOGGER.warning("⚠️ [Eitaa] Attach button not found, trying one more refresh...")
            br.refresh()
            time.sleep(3)
            WebDriverWait(br, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".attach-file")))
        
        tag_name = f"data-tag-{uuid.uuid4().hex[:8]}"
        caption = text if text else ""
        
        if file_paths:
            timeout = 120 + (len(file_paths) * 30)
            if len(caption) > 1626:
                LOGGER.info(f"✂️ [Eitaa] Caption exceeds limit ({len(caption)} chars). Sending media without text first...")
                media_success = send_media(br, file_paths, "", tag_name, timeout)
                if media_success:
                    LOGGER.info("📝 [Eitaa] Media sent. Now sending the long caption as a separate text message...")
                    time.sleep(2)
                    text_tag = f"data-tag-{uuid.uuid4().hex[:8]}"
                    return send_text(br, caption, text_tag, 30)
                return media_success
            else:
                return send_media(br, file_paths, caption, tag_name, timeout)
        else:
            return send_text(br, caption, tag_name, 30)
            
    except Exception as e:
        LOGGER.error(f"❌ [Eitaa] Critical Error processing message: {e}")
        return False

_eitaa_lock = None
def get_eitaa_lock():
    global _eitaa_lock
    if _eitaa_lock is None:
        _eitaa_lock = asyncio.Lock()
    return _eitaa_lock

async def send_to_eitaa(text: str = None, file_path: str = None, file_type: str = None, filename: str = None, chat_id: str = None):
    if not chat_id: return False
    paths = [os.path.abspath(file_path)] if file_path else []
    
    LOGGER.info(f"📤 [Eitaa] Queueing single message for {chat_id}")
    
    async with get_eitaa_lock():
        success = await asyncio.to_thread(process_eitaa_message, text, paths, chat_id)
    return success

async def send_album_to_eitaa(media_items: list, chat_id: str = None):
    if not chat_id or not media_items: return False
    paths = [os.path.abspath(item['path']) for item in media_items]
    caption = media_items[0].get('caption', "")
    
    LOGGER.info(f"📤 [Eitaa] Queueing album ({len(paths)} files) for {chat_id}")
    
    async with get_eitaa_lock():
        success = await asyncio.to_thread(process_eitaa_message, caption, paths, chat_id)
    return success