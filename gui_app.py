import sys
import threading
import tkinter as tk
from tkinter import scrolledtext
import pystray
from PIL import Image
import os
import logging
import queue
import json
import subprocess

from main import run as start_bot

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_config_path():
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, "proxy_config.json")

class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put(msg)
        except Exception:
            self.handleError(record)

# --- کلاس‌های جدید برای شبیه‌سازی ترمینال ---
class GUIStdin:
    def __init__(self):
        self.input_queue = queue.Queue()

    def readline(self):
        # متوقف کردن ترد پس‌زمینه (Telethon) تا زمانی که کاربر متنی را در محیط گرافیکی ارسال کند
        return self.input_queue.get() + '\n'
        
    def write(self, text):
        pass
        
    def flush(self):
        pass

class GUIStdout:
    def __init__(self, log_queue):
        self.log_queue = log_queue
        self.buffer = ""

    def write(self, msg):
        if msg:
            self.buffer += msg
            if '\n' in self.buffer:
                lines = self.buffer.split('\n')
                for line in lines[:-1]:
                    # فیلتر کردن لاگ‌های core.py (که با کروشه شروع میشوند) برای جلوگیری از چاپ دوگانه
                    if line.strip() and not line.strip().startswith("["):
                        self.log_queue.put(f"[ Terminal ] {line.strip()}")
                self.buffer = lines[-1]

    def flush(self):
        pass
# ---------------------------------------------

class BotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Manager")
        self.root.geometry("650x600") # ارتفاع بیشتر برای باکس ورودی
        self.bot_thread = None
        self.icon_image_path = resource_path("icon1.png")

        self.setup_logging()

        # اتصال ورودی و خروجی استاندارد به رابط گرافیکی برای احراز هویت تلگرام
        self.gui_stdin = GUIStdin()
        sys.stdin = self.gui_stdin
        sys.stdout = GUIStdout(self.log_queue)

        if os.path.exists(self.icon_image_path):
            try:
                img = tk.PhotoImage(file=self.icon_image_path)
                self.root.iconphoto(True, img)
            except Exception as e:
                logging.error(f"Error loading window icon: {e}")

        # --- بخش تنظیمات پروکسی ---
        self.proxy_frame = tk.LabelFrame(root, text="Proxy Settings")
        self.proxy_frame.pack(pady=10, padx=10, fill=tk.X)

        self.proxy_enable_var = tk.BooleanVar()
        tk.Checkbutton(self.proxy_frame, text="Use Proxy", variable=self.proxy_enable_var).grid(row=0, column=0, padx=5, pady=5)

        tk.Label(self.proxy_frame, text="Protocol:").grid(row=0, column=1)
        self.proxy_type_var = tk.StringVar(value="socks5")
        tk.OptionMenu(self.proxy_frame, self.proxy_type_var, "http", "socks4", "socks5").grid(row=0, column=2, padx=5)

        tk.Label(self.proxy_frame, text="IP").grid(row=1, column=0, pady=5)
        self.proxy_ip_var = tk.StringVar(value="127.0.0.1")
        tk.Entry(self.proxy_frame, textvariable=self.proxy_ip_var, width=15).grid(row=1, column=1, padx=5)

        tk.Label(self.proxy_frame, text="Port").grid(row=1, column=2)
        self.proxy_port_var = tk.StringVar(value="10808")
        tk.Entry(self.proxy_frame, textvariable=self.proxy_port_var, width=8).grid(row=1, column=3, padx=5)

        tk.Button(self.proxy_frame, text="Save Proxy", command=self.save_proxy, bg="#f0ad4e").grid(row=1, column=4, padx=15)

        self.load_proxy_settings()

        # --- دکمه‌های کنترلی ---
        self.btn_frame = tk.Frame(root)
        self.btn_frame.pack(pady=5)

        self.start_btn = tk.Button(self.btn_frame, text="Start Bot", command=self.start_bot_thread, bg="#5cb85c", fg="white", width=12)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.hide_btn = tk.Button(self.btn_frame, text="Hide Window", command=self.hide_window, bg="#5bc0de", fg="white", width=12)
        self.hide_btn.pack(side=tk.LEFT, padx=5)

        self.exit_btn = tk.Button(self.btn_frame, text="Force Exit", command=self.force_exit, bg="#d9534f", fg="white", width=12)
        self.exit_btn.pack(side=tk.LEFT, padx=5)

        self.autostart_var = tk.BooleanVar()
        self.autostart_check = tk.Checkbutton(root, text="Auto Start with Windows", variable=self.autostart_var, command=self.toggle_autostart)
        self.autostart_check.pack(pady=2)

        # --- نمایش لاگ‌ها (بهینه شده) ---
        tk.Label(root, text="System Logs (Max 100 lines visible):").pack(anchor="w", padx=10)
        self.log_area = scrolledtext.ScrolledText(root, state='disabled', bg='black', fg='#00FF00', font=("Consolas", 9))
        self.log_area.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        # --- خط فرمان تعاملی برای ورود کد/تاییدیه‌ها ---
        self.input_frame = tk.Frame(root)
        self.input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.cmd_entry = tk.Entry(self.input_frame, bg="#282a36", fg="white", font=("Consolas", 10))
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cmd_entry.bind("<Return>", self.send_to_terminal)
        
        self.send_btn = tk.Button(self.input_frame, text="Send ↵", command=self.send_to_terminal, bg="#44475a", fg="white")
        self.send_btn.pack(side=tk.RIGHT, padx=5)

        self.root.protocol('WM_DELETE_WINDOW', self.hide_window)
        
        self.root.after(100, self.update_logs)
        logging.info("The user interface is ready. Starting the robot...")
        self.root.after(1500, self.start_bot_thread)

    def setup_logging(self):
        self.log_queue = queue.Queue()
        queue_handler = QueueLogHandler(self.log_queue)
        formatter = logging.Formatter("[ %(asctime)s ] %(message)s", "%H:%M:%S")
        queue_handler.setFormatter(formatter)
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(queue_handler)
        
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("telethon").setLevel(logging.INFO)

    def update_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_area.configure(state='normal')
                self.log_area.insert(tk.END, msg + '\n')
                
                # مدیریت حافظه: پاک کردن خطوط قدیمی، نگه‌داشتن فقط ۱۰۰ خط آخر
                num_lines = int(self.log_area.index('end-1c').split('.')[0])
                if num_lines > 100:
                    self.log_area.delete('1.0', f"{num_lines - 100}.0")
                    
                self.log_area.configure(state='disabled')
                self.log_area.yview(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self.update_logs)

    def send_to_terminal(self, event=None):
        text = self.cmd_entry.get().strip()
        if text:
            # نمایش مقدار ارسال شده در کنسول با علامت >>>
            self.log_area.configure(state='normal')
            self.log_area.insert(tk.END, f">>> {text}\n")
            self.log_area.configure(state='disabled')
            self.log_area.yview(tk.END)
            
            # ارسال متن به ترد ربات که منتظر تابع ()input است
            self.gui_stdin.input_queue.put(text)
            self.cmd_entry.delete(0, tk.END)

    def load_proxy_settings(self):
        config_path = get_config_path()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.proxy_enable_var.set(config.get("PROXY_ENABLE", False))
                    self.proxy_type_var.set(config.get("PROXY_TYPE", "socks5"))
                    self.proxy_ip_var.set(config.get("PROXY_IP", "127.0.0.1"))
                    self.proxy_port_var.set(config.get("PROXY_PORT", "10808"))
            except Exception as e:
                logging.error(f"خطا در خواندن فایل تنظیمات پروکسی: {e}")

    def save_proxy(self):
        config_path = get_config_path()
        config = {
            "PROXY_ENABLE": self.proxy_enable_var.get(),
            "PROXY_TYPE": self.proxy_type_var.get(),
            "PROXY_IP": self.proxy_ip_var.get(),
            "PROXY_PORT": self.proxy_port_var.get()
        }
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            logging.info("✅ تنظیمات پروکسی ذخیره شد. برنامه تا ۲ ثانیه دیگر ری‌استارت می‌شود...")
            self.root.after(2000, self.restart_application)
        except Exception as e:
            logging.error(f"❌ خطا در ذخیره تنظیمات پروکسی: {e}")

    def restart_application(self):
        logging.info("🔄 در حال بستن و راه‌اندازی مجدد برنامه...")
        logging.shutdown()  # 🔥 تغییر مهم: ذخیره قطعی تمام لاگ‌ها در فایل قبل از ری‌استارت
        if hasattr(self, 'tray_icon'): 
            self.tray_icon.stop()
            
        subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)

    def start_bot_thread(self):
        if self.bot_thread is None or not self.bot_thread.is_alive():
            self.bot_thread = threading.Thread(target=start_bot, daemon=True)
            self.bot_thread.start()
            logging.info("🚀 The robot was activated in the background layer...")

    def hide_window(self):
        self.root.withdraw()
        if os.path.exists(self.icon_image_path):
            image = Image.open(self.icon_image_path)
        else:
            image = Image.new('RGB', (64, 64), color=(33, 150, 243))
            
        menu = (pystray.MenuItem('نمایش', self.show_window), pystray.MenuItem('خروج', self.force_exit))
        self.tray_icon = pystray.Icon("bot_fwd", image, "Bot Forwarder", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_window(self, icon, item):
        self.tray_icon.stop()
        self.root.after(0, self.root.deiconify)

    def force_exit(self, icon=None, item=None):
        logging.info("در حال بستن کامل فرآیندها...")
        logging.shutdown()  # 🔥 تغییر مهم: ذخیره قطعی تمام لاگ‌ها در فایل قبل از خروج
        if hasattr(self, 'tray_icon'): self.tray_icon.stop()
        os._exit(0)

    def toggle_autostart(self):
        if sys.platform == "win32":
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
                    if self.autostart_var.get():
                        winreg.SetValueEx(key, "BotForwarder", 0, winreg.REG_SZ, sys.executable)
                        logging.info("➕ اجرای خودکار فعال شد.")
                    else:
                        try:
                            winreg.DeleteValue(key, "BotForwarder")
                            logging.info("➖ اجرای خودکار غیرفعال شد.")
                        except FileNotFoundError: pass
            except Exception as e:
                logging.error(f"خطا در تنظیم اجرای خودکار: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = BotApp(root)
    root.mainloop()