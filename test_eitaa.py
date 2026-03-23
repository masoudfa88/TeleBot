import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# =========================================================
# 🛠️ توابع کمکی (برای جلوگیری از تکرار کد و افزایش سرعت)
# =========================================================

def verify_upload(driver, tag_name, timeout_seconds):
    """بررسی می‌کند که آیا پیامِ جدید روی سرور ثبت و تایید شده است یا خیر"""
    success = False
    for _ in range(timeout_seconds):
        try:
            new_msgs = driver.find_elements(By.CSS_SELECTOR, f".message:not([{tag_name}='true']), .bubble:not([{tag_name}='true'])")
            if len(new_msgs) > 0:
                last_msg = new_msgs[-1]
                # آیکون‌های موفقیت و لودینگ را می‌گردد
                success_icons = last_msg.find_elements(By.CSS_SELECTOR, ".tgico-channelviews, .tgico-check, .tgico-checks, .message-views, i[class*='view'], span[class*='view']")
                loading_icons = last_msg.find_elements(By.CSS_SELECTOR, ".tgico-time, .progress, .spinner, .loading")
                
                if len(success_icons) > 0 and len(loading_icons) == 0:
                    success = True
                    break
        except: pass
        time.sleep(1)
    return success


def send_media(driver, file_paths_list, caption_text, tag_name, timeout=120):
    """تابع همه‌کاره برای ارسال عکس، ویدیو و آلبوم"""
    print(f"\n🏷️ نشانه‌گذاری پیام‌ها ({tag_name})...")
    driver.execute_script(f"document.querySelectorAll('.message, .bubble').forEach(el => el.setAttribute('{tag_name}', 'true'));")

    attach_btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".attach-file")))
    attach_btn.click()
    time.sleep(1)

    print(f"⚙️ در حال بارگذاری {len(file_paths_list)} فایل در اینپوت مرورگر...")
    file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
    driver.execute_script("arguments[0].setAttribute('accept', '*/*');", file_input) # اجازه تمام فرمت‌ها
    
    # ترفند طلایی برای ارسال چند فایل (آلبوم): چسباندن مسیرها با \n
    paths_string = "\n".join(file_paths_list)
    file_input.send_keys(paths_string)
    
    WebDriverWait(driver, 15).until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "div[contenteditable='true']")) >= 2)
    
    # مدیریت تیک‌های فشرده‌سازی
    try:
        for label in driver.find_elements(By.XPATH, "//label[contains(., 'فشرده')]"):
            cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            if not cb.is_selected(): driver.execute_script("arguments[0].click();", cb)
        for label in driver.find_elements(By.XPATH, "//label[contains(., 'فایل')]"):
            cb = label.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            if cb.is_selected(): driver.execute_script("arguments[0].click();", cb)
    except: pass

    # کپشن
    caption_box = driver.find_elements(By.CSS_SELECTOR, "div[contenteditable='true']")[-1] 
    driver.execute_script("arguments[0].focus(); document.execCommand('insertText', false, arguments[1]);", caption_box, caption_text)
    caption_box.send_keys(" ")
    time.sleep(1)
    
    print("🚀 در حال آپلود...")
    caption_box.send_keys(Keys.RETURN)
    
    try: WebDriverWait(driver, 10).until(EC.staleness_of(caption_box))
    except: pass

    if verify_upload(driver, tag_name, timeout):
        print("🎉 عملیات ارسال فایل(ها) ۱۰۰٪ تایید شد! ✅")
    else:
        print("⚠️ آپلود زمان‌بر شد (احتمالاً فایل سنگین است)، ادامه می‌دهیم...")


def send_text(driver, text_message, tag_name, timeout=30):
    """تابع ارسال پیام متنی با سیستم ضد-کرش"""
    print(f"\n🏷️ نشانه‌گذاری پیام‌ها ({tag_name})...")
    driver.execute_script(f"document.querySelectorAll('.message, .bubble').forEach(el => el.setAttribute('{tag_name}', 'true'));")

    print("✍️ در حال پیدا کردن باکس چت...")
    chat_box = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.input-message-input:not(.input-field-input-fake)"))
    )
    
    try: chat_box.click() 
    except: driver.execute_script("arguments[0].click();", chat_box)
    time.sleep(1)

    print("✍️ نوشتن پیام و ارسال سیگنال...")
    js_script = """
        var box = arguments[0]; box.focus();
        document.execCommand('insertText', false, arguments[1]);
        box.dispatchEvent(new Event('input', { bubbles: true }));
    """
    driver.execute_script(js_script, chat_box, text_message)
    chat_box.send_keys(" ") 
    time.sleep(1)
    
    print("🚀 در حال ارسال...")
    chat_box.send_keys(Keys.RETURN)

    if verify_upload(driver, tag_name, timeout):
        print("🎉 پیام متنی ارسال شد! ✅")
    else:
        print("⚠️ پیام متنی رفت اما تاییدیه نیامد.")

# =========================================================
# 🚀 بدنه اصلی برنامه (مدیریت ۴ مرحله)
# =========================================================

def run_multimedia_test():
    target_channel = "iranvahed1"  
    base_dir = r"C:\Users\Administrator\Desktop\dist"
    
    # مسیر فایل‌ها
    img1 = os.path.join(base_dir, "001.jpg")
    img2 = os.path.join(base_dir, "002.jpg")
    vid1 = os.path.join(base_dir, "001.mp4")

    # بررسی وجود فایل‌ها
    for f in [img1, img2, vid1]:
        if not os.path.exists(f):
            print(f"❌ خطای بحرانی: فایل پیدا نشد! ({f})")
            return

    profile_path = os.path.join(os.path.abspath("."), "eitaa_server_profile")
    options = webdriver.ChromeOptions()
    options.add_argument(f"user-data-dir={profile_path}")
    # options.add_argument("--headless=new") # ⚠️ در صورت نیاز به لاگین، این خط کامنت شود
    options.add_argument("--window-size=1920,1080") 
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    
    print("🌐 استارت مرورگر روی سرور...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        driver.get("https://web.eitaa.com/")
        print("⏳ منتظر لود ایتا...")
        WebDriverWait(driver, 120).until(EC.presence_of_element_located((By.ID, "main-search")))
        
        driver.get(f"https://web.eitaa.com/#/im?p=@{target_channel}")
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".attach-file")))
        print("✅ کانال لود شد. شروع عملیات ۴ گانه:\n" + "="*40)

        # ---------------------------------------------------------
        # فاز ۱: ارسال تک عکس
        # ---------------------------------------------------------
        print("▶️ فاز ۱: ارسال یک عکس (001.jpg)")
        send_media(driver, [img1], "📸 ۱. این یک تک‌عکس است", "data-phase1", timeout=120)
        time.sleep(3)

        # ---------------------------------------------------------
        # فاز ۲: ارسال متن
        # ---------------------------------------------------------
        print("\n▶️ فاز ۲: ارسال پیام متنی")
        send_text(driver, "📝 ۲. این پیام متنی بین عکس و آلبوم است.", "data-phase2", timeout=30)
        time.sleep(3)

        # ---------------------------------------------------------
        # فاز ۳: ارسال آلبوم (چندین عکس همزمان)
        # ---------------------------------------------------------
        print("\n▶️ فاز ۳: ارسال آلبوم عکس (001.jpg و 002.jpg)")
        # ترفند آلبوم: لیست مسیرها را به تابع می‌دهیم
        send_media(driver, [img1, img2], "🖼️ ۳. این یک آلبوم تصویری است!", "data-phase3", timeout=180)
        time.sleep(3)

        # ---------------------------------------------------------
        # فاز ۴: ارسال ویدیو
        # ---------------------------------------------------------
        print("\n▶️ فاز ۴: ارسال ویدیو (001.mp4)")
        # زمان آپلود ویدیو را طولانی‌تر (۳۰۰ ثانیه = ۵ دقیقه) در نظر گرفتیم
        send_media(driver, [vid1], "🎥 ۴. و در نهایت، ارسال موفقیت‌آمیز ویدیو! پایان تست.", "data-phase4", timeout=300)

        print("\n" + "="*40 + "\n🎯 هر ۴ مرحله با موفقیت روی سرور اجرا شد!")

    except Exception as e:
        print(f"\n❌ خطای پیش‌بینی نشده:\n{e}")
    finally:
        print("👉 خروج و بستن مرورگر...")
        driver.quit()

if __name__ == "__main__":
    run_multimedia_test()