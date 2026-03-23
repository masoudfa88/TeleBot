import os
import sys
import subprocess

def build_gui():
    print("Building GUI Executable (Single File)...")
    
    separator = ";" if sys.platform == "win32" else ":"
    base_dir = os.path.abspath(os.path.dirname(__file__))
    
    icon_path = os.path.join(base_dir, "icon1.png")
    env_path = os.path.join(base_dir, ".env")
    script_path = os.path.join(base_dir, "gui_app.py")
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--collect-all", "selenium",  # 👈 این خط اضافه شد تا سلنیوم جا نماند
        "--name", "TelegramForwarderBot"
    ]

    if os.path.exists(icon_path):
        cmd.append(f"--add-data={icon_path}{separator}.")
        cmd.append(f"--icon={icon_path}")
    else:
        print("⚠️ Warning: icon1.png not found. Building without icon.")

    if os.path.exists(env_path):
        cmd.append(f"--add-data={env_path}{separator}.")
        print("✅ .env file included in build.")
    else:
        print("⚠️ Warning: .env not found. Building without it.")

    cmd.append(script_path)
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("✅ Build Completed! Check the 'dist' folder.")
    else:
        print("❌ Build Failed! Please check the error logs above.")

def build_server():
    print("Generating Server Setup Script...")
    script = """#!/bin/bash
echo "Setting up headless bot for Linux Server..."
pip install -r requirements.txt
cat <<EOT > /etc/systemd/system/tgbot.service
[Unit]
Description=Telegram Forwarder Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(which python3) $(pwd)/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOT

systemctl daemon-reload
systemctl enable tgbot
systemctl start tgbot
echo "✅ Bot is running in background. Logs are in bot_logs.log"
"""
    with open("setup_server.sh", "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod("setup_server.sh", 0o755)
    print("✅ Generated setup_server.sh. Run it on your linux server with sudo.")

if __name__ == "__main__":
    print("1. Build for Windows/Ubuntu Desktop (GUI Executable)")
    print("2. Generate Linux Server Headless Deployment Script")
    choice = input("Enter your choice (1/2): ")
    
    if choice == '1':
        build_gui()
    elif choice == '2':
        build_server()
    else:
        print("Invalid choice.")