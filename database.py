import aiosqlite
import os
import sys
import time

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(application_path, "bot_data.db")

# دیکشنری موقت برای ذخیره کپشن اصلی آلبوم‌ها (برای ویرایش و انتشار)
ALBUM_CAPTIONS = {}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                license_key TEXT PRIMARY KEY,
                is_used BOOLEAN DEFAULT 0,
                used_by INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER,
                channel_id INTEGER,
                channel_title TEXT,
                channel_username TEXT,
                UNIQUE(user_id, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS remove_words (
                user_id INTEGER,
                word TEXT,
                UNIQUE(user_id, word)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                user_id INTEGER,
                channel_id TEXT,
                append_text TEXT,
                UNIQUE(user_id, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mappings (
                user_id INTEGER,
                source_id TEXT,
                target_id TEXT,
                mode TEXT,
                UNIQUE(user_id, source_id, target_id)
            )
        """)
        
        # 👇 این بخش برای ساخت جدول آمار روزانه اضافه شد 👇
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                user_id INTEGER,
                source_id TEXT,
                fetched_count INTEGER DEFAULT 0,
                tg_sent_count INTEGER DEFAULT 0,
                bale_sent_count INTEGER DEFAULT 0,
                eitaa_sent_count INTEGER DEFAULT 0,
                UNIQUE(user_id, source_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bale_targets (
                user_id INTEGER,
                channel_id TEXT,
                append_text TEXT,
                UNIQUE(user_id, channel_id)
            )
        """)
                
        # تلاش زوری برای اضافه کردن ستون ایتا به دیتابیس‌های ساخته شده‌ی قدیمی
        try:
            await db.execute("ALTER TABLE daily_stats ADD COLUMN eitaa_sent_count INTEGER DEFAULT 0")
        except:
            pass
        # 👆 ------------------------------------------- 👆
        try:
            await db.execute("ALTER TABLE users ADD COLUMN active_license TEXT")
        except: pass
        
        try:
            await db.execute("ALTER TABLE licenses ADD COLUMN max_users INTEGER DEFAULT 1")
            await db.execute("ALTER TABLE licenses ADD COLUMN max_sources INTEGER DEFAULT 1000")
            await db.execute("ALTER TABLE licenses ADD COLUMN max_targets INTEGER DEFAULT 1000")
            await db.execute("ALTER TABLE licenses ADD COLUMN owner_id INTEGER")
        except: pass

        # سازگار کردن لایسنس فعال فعلی شما با سیستم جدید (جلوگیری از اختلال)
        await db.execute("UPDATE users SET active_license = (SELECT license_key FROM licenses WHERE used_by = users.user_id LIMIT 1) WHERE active_license IS NULL")
        await db.execute("UPDATE licenses SET owner_id = used_by WHERE owner_id IS NULL AND is_used = 1")
        try:
            async with db.execute("SELECT user_id, channel_id, append_text FROM target_channels") as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    await db.execute("INSERT OR IGNORE INTO targets (user_id, channel_id, append_text) VALUES (?, ?, ?)", r)
        except Exception:
            pass

        await db.commit()
        
# 2. تابع جدید برای پیدا کردن شناسه مالک (Owner)
async def get_owner(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT l.owner_id 
            FROM users u 
            LEFT JOIN licenses l ON u.active_license = l.license_key 
            WHERE u.user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
            return user_id
        
# --- توابع کاربر و لایسنس ---
async def check_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, is_active FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def add_license(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO licenses (license_key) VALUES (?)", (license_key,))
        await db.commit()

# تابع تولید لایسنس ادمین با تنظیمات
async def add_advanced_license(license_key: str, max_users: int, max_sources: int, max_targets: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO licenses 
            (license_key, max_users, max_sources, max_targets) 
            VALUES (?, ?, ?, ?)
        """, (license_key, max_users, max_sources, max_targets))
        await db.commit()
    
async def get_all_licenses():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT l.license_key, l.is_used, l.used_by, u.name, l.max_users, l.max_sources, l.max_targets 
            FROM licenses l 
            LEFT JOIN users u ON l.used_by = u.user_id
        ''') as cursor:
            return await cursor.fetchall()

async def update_license_limits(license_key: str, max_users: int, max_sources: int, max_targets: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE licenses 
            SET max_users = ?, max_sources = ?, max_targets = ? 
            WHERE license_key = ?
        """, (max_users, max_sources, max_targets, license_key))
        await db.commit()
        
# 3. بازنویسی سیستم ثبت لایسنس
async def use_license(user_id: int, name: str, license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT max_users, owner_id FROM licenses WHERE license_key = ?", (license_key,)) as cursor:
            row = await cursor.fetchone()
            if not row: return False # لایسنس وجود ندارد
            max_users, owner_id = row

        # بررسی تعداد کاربرانی که الان دارند از این لایسنس استفاده می‌کنند
        async with db.execute("SELECT COUNT(*) FROM users WHERE active_license = ?", (license_key,)) as cursor:
            current_users = (await cursor.fetchone())[0]

        # بررسی اینکه آیا خود این کاربر از قبل عضو این لایسنس هست یا نه
        async with db.execute("SELECT user_id FROM users WHERE user_id = ? AND active_license = ?", (user_id, license_key)) as cursor:
            already_using = await cursor.fetchone()

        if not already_using and current_users >= max_users:
            return "FULL" # ظرفیت تکمیل است

        if owner_id is None:
            # اولین نفری که لایسنس را میزند مالک می‌شود
            owner_id = user_id
            await db.execute("UPDATE licenses SET is_used = 1, owner_id = ?, used_by = ? WHERE license_key = ?", (owner_id, owner_id, license_key))
        
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as u_cursor:
            if await u_cursor.fetchone():
                await db.execute("UPDATE users SET name = ?, is_active = 1, active_license = ? WHERE user_id = ?", (name, license_key, user_id))
            else:
                await db.execute("INSERT INTO users (user_id, name, is_active, active_license) VALUES (?, ?, 1, ?)", (user_id, name, license_key))
                
        await db.commit()
        return True

# 4. توابع بررسی محدودیت‌ها
async def get_license_limits(owner_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT max_sources, max_targets FROM licenses WHERE owner_id = ?", (owner_id,)) as cursor:
            row = await cursor.fetchone()
            return row if row else (1000, 1000)

async def check_source_limit(owner_id: int):
    limits = await get_license_limits(owner_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ?", (owner_id,)) as cursor:
            count = (await cursor.fetchone())[0]
    return count < limits[0]

async def check_target_limit(owner_id: int):
    limits = await get_license_limits(owner_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM targets WHERE user_id = ?", (owner_id,)) as c1:
            t1 = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM bale_targets WHERE user_id = ?", (owner_id,)) as c2:
            t2 = (await c2.fetchone())[0]
    return (t1 + t2) < limits[1]

async def delete_license(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE active_license = ?", (license_key,)) as cursor:
            users_to_deactivate = [row[0] for row in await cursor.fetchall()]
        
        await db.execute("UPDATE users SET is_active = 0, active_license = NULL WHERE active_license = ?", (license_key,))
        await db.execute("DELETE FROM licenses WHERE license_key = ?", (license_key,))
        await db.commit()
        
        return users_to_deactivate

async def change_user_license(user_id: int, new_license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            name = row[0] if row else "کاربر"
            
    return await use_license(user_id, name, new_license_key)

async def update_user_name(user_id: int, new_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET name = ? WHERE user_id = ?", (new_name, user_id))
        await db.commit()

# --- توابع کانال مبدأ ---
async def add_subscription(user_id: int, channel_id: int, title: str, username: str = None):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions (user_id, channel_id, channel_title, channel_username) VALUES (?, ?, ?, ?)", (user_id, channel_id, title, username))
        await db.commit()

async def get_subscribers(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # تنها کاربرانی که is_active = 1 هستند پیام‌ها را دریافت می‌کنند
        async with db.execute('''
            SELECT s.user_id 
            FROM subscriptions s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.channel_id = ? AND u.is_active = 1
        ''', (channel_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_channel_title(user_id: int, channel_id: int):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_title FROM subscriptions WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "نامشخص"

async def get_user_subscriptions(user_id: int):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute("SELECT channel_id, channel_title, channel_username FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchall()
        except Exception:
            async with db.execute("SELECT channel_id, channel_title FROM subscriptions WHERE user_id = ?", (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [(row[0], row[1], None) for row in rows]

async def delete_subscription_by_id(user_id: int, channel_id: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM mappings WHERE user_id = ? AND source_id = ?", (user_id, str(channel_id)))
        await db.execute("DELETE FROM subscriptions WHERE user_id = ? AND CAST(channel_id AS TEXT) = ?", (user_id, channel_id))
        await db.commit()

# --- توابع حذف کلمات ---
async def add_remove_word(user_id: int, word: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO remove_words (user_id, word) VALUES (?, ?)", (user_id, word))
        await db.commit()

async def get_remove_words(user_id: int):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM remove_words WHERE user_id = ?", (user_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

# --- توابع کانال مقصد ---
async def add_target(user_id: int, channel_id: str, append_text: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO targets (user_id, channel_id, append_text) VALUES (?, ?, ?)", (user_id, channel_id, append_text))
        await db.commit()

async def get_targets(user_id: int):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM targets WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

async def get_target_by_id(user_id: int, channel_id: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM targets WHERE user_id = ? AND channel_id = ?", (user_id, channel_id)) as cursor:
            return await cursor.fetchone()

async def delete_target(user_id: int, channel_id: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM targets WHERE user_id = ? AND channel_id = ?", (user_id, channel_id))
        await db.execute("DELETE FROM mappings WHERE user_id = ? AND target_id = ?", (user_id, channel_id))
        await db.commit()

# --- توابع نگاشت کانال‌ها ---
async def set_mapping(user_id: int, source_id: str, target_id: str, mode: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        if mode == 'none':
            await db.execute("DELETE FROM mappings WHERE user_id = ? AND source_id = ? AND target_id = ?", (user_id, source_id, target_id))
        else:
            await db.execute("INSERT OR REPLACE INTO mappings (user_id, source_id, target_id, mode) VALUES (?, ?, ?, ?)", (user_id, source_id, target_id, mode))
        await db.commit()

async def get_mappings(user_id: int, source_id: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT target_id, mode FROM mappings WHERE user_id = ? AND source_id = ?", (user_id, str(source_id))) as cursor:
            return await cursor.fetchall()
async def init_cache_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS post_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_unique_id TEXT,
                phash TEXT,
                normalized_text TEXT,
                timestamp INTEGER
            )
        """)
        try:
            await db.execute("ALTER TABLE post_cache ADD COLUMN target_id TEXT")
        except:
            pass
        await db.commit()

async def add_to_cache(target_id: str, file_unique_id: str, phash: str, normalized_text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO post_cache (target_id, file_unique_id, phash, normalized_text, timestamp) VALUES (?, ?, ?, ?, ?)",
            (str(target_id), file_unique_id, phash, normalized_text, int(time.time()))
        )
        await db.commit()

async def get_recent_cache(target_id: str):
    # دریافت پیام‌های ۳ ساعت گذشته (۱۰۸۰۰ ثانیه)
    three_hours_ago = int(time.time()) - 10800
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_unique_id, phash, normalized_text FROM post_cache WHERE timestamp > ? AND (target_id = ? OR target_id IS NULL)", 
            (three_hours_ago, str(target_id))
        ) as cursor:
            return await cursor.fetchall()

async def cleanup_cache():
    three_hours_ago = int(time.time()) - 10800
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_cache WHERE timestamp <= ?", (three_hours_ago,))
        await db.commit()
        
async def delete_remove_word(user_id: int, word: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM remove_words WHERE user_id = ? AND word = ?", (user_id, word))
        await db.commit()
        
async def get_unique_source_channels():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute("SELECT DISTINCT channel_id FROM subscriptions") as cursor:
            return [row[0] for row in await cursor.fetchall()]
        
async def init_stats_table():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                user_id INTEGER,
                source_id TEXT,
                fetched_count INTEGER DEFAULT 0,
                tg_sent_count INTEGER DEFAULT 0,
                bale_sent_count INTEGER DEFAULT 0,
                eitaa_sent_count INTEGER DEFAULT 0,
                UNIQUE(user_id, source_id)
            )
        """)
        # تلاش زوری برای اضافه کردن ستون ایتا به دیتابیس‌های ساخته شده‌ی قدیمی
        try:
            await db.execute("ALTER TABLE daily_stats ADD COLUMN eitaa_sent_count INTEGER DEFAULT 0")
        except:
            pass
        # تلاش برای آپدیت جدول قدیمی (برای کسانی که جدول را از قبل داشتند)
        try:
            await db.execute("ALTER TABLE daily_stats ADD COLUMN eitaa_sent_count INTEGER DEFAULT 0")
        except:
            pass
        await db.commit()

async def increment_stat(user_id: int, source_id: str, stat_type: str, count: int = 1):
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        await db.execute(f"""
            INSERT INTO daily_stats (user_id, source_id, {stat_type})
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, source_id)
            DO UPDATE SET {stat_type} = {stat_type} + ?
        """, (user_id, str(source_id), count, count))
        await db.commit()

async def get_all_daily_stats():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute("SELECT user_id, source_id, fetched_count, tg_sent_count, bale_sent_count, eitaa_sent_count FROM daily_stats") as cursor:
            return await cursor.fetchall()

async def reset_daily_stats():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        await db.execute("DELETE FROM daily_stats")
        await db.commit()

# --- توابع کانال مقصد بله ---
async def add_bale_target(user_id: int, channel_id: str, append_text: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bale_targets (user_id, channel_id, append_text) VALUES (?, ?, ?)", (user_id, channel_id, append_text))
        await db.commit()

async def get_bale_targets(user_id: int):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM bale_targets WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchall()

async def delete_bale_target(user_id: int, channel_id: str):
    user_id = await get_owner(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bale_targets WHERE user_id = ? AND channel_id = ?", (user_id, channel_id))
        await db.commit()