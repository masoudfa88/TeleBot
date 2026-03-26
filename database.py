import aiosqlite
import os
import sys
import time
from core import bot, LOGGER

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(application_path, "bot_data.db")

ALBUM_CAPTIONS = {}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                license_key TEXT PRIMARY KEY,
                name TEXT,
                max_users INTEGER DEFAULT 1,
                max_sources INTEGER DEFAULT 1000,
                max_targets INTEGER DEFAULT 1000,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                active_license TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                license_key TEXT,
                channel_id INTEGER,
                channel_title TEXT,
                channel_username TEXT,
                UNIQUE(license_key, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                license_key TEXT,
                channel_id TEXT,
                append_text TEXT,
                UNIQUE(license_key, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bale_targets (
                license_key TEXT,
                channel_id TEXT,
                append_text TEXT,
                UNIQUE(license_key, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS eitaa_targets (
                license_key TEXT,
                channel_id TEXT,
                append_text TEXT,
                UNIQUE(license_key, channel_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS remove_words (
                license_key TEXT,
                word TEXT,
                UNIQUE(license_key, word)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS forbidden_words (
                license_key TEXT,
                word TEXT,
                UNIQUE(license_key, word)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mappings (
                license_key TEXT,
                source_id TEXT,
                target_id TEXT,
                mode TEXT,
                UNIQUE(license_key, source_id, target_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                license_key TEXT,
                source_id TEXT,
                fetched_count INTEGER DEFAULT 0,
                tg_sent_count INTEGER DEFAULT 0,
                bale_sent_count INTEGER DEFAULT 0,
                eitaa_sent_count INTEGER DEFAULT 0,
                UNIQUE(license_key, source_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS post_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT,
                target_id TEXT,
                file_unique_id TEXT,
                phash TEXT,
                normalized_text TEXT,
                timestamp INTEGER
            )
        """)
        await db.commit()
        LOGGER.info("✅ Database created and loaded with License-Based architecture.")

# --- توابع پایه لایسنس ---
async def get_user_license(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT l.license_key, l.is_active 
            FROM users u 
            JOIN licenses l ON u.active_license = l.license_key 
            WHERE u.user_id = ?
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[1] == 1:
                return row[0]
            return None

async def add_advanced_license(license_key: str, name: str, max_users: int, max_sources: int, max_targets: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO licenses 
            (license_key, name, max_users, max_sources, max_targets, is_active) 
            VALUES (?, ?, ?, ?, ?, 1)
        """, (license_key, name, max_users, max_sources, max_targets))
        await db.commit()

async def get_all_licenses():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT license_key, name, max_users, max_sources, max_targets, is_active
            FROM licenses
        ''') as cursor:
            licenses = await cursor.fetchall()
        
        result = []
        for lic in licenses:
            lic_key, name, max_users, max_src, max_tgt, is_active = lic
            
            async with db.execute("SELECT name FROM users WHERE active_license = ?", (lic_key,)) as c:
                users_list = [row[0] for row in await c.fetchall()]
            
            async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE license_key = ?", (lic_key,)) as c:
                current_src = (await c.fetchone())[0]
                
            async with db.execute("SELECT COUNT(*) FROM targets WHERE license_key = ?", (lic_key,)) as c:
                t1 = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM bale_targets WHERE license_key = ?", (lic_key,)) as c:
                t2 = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM eitaa_targets WHERE license_key = ?", (lic_key,)) as c:
                t3 = (await c.fetchone())[0]
            current_tgt = t1 + t2 + t3
                
            result.append({
                'license_key': lic_key,
                'name': name,
                'max_users': max_users,
                'max_sources': max_src,
                'max_targets': max_tgt,
                'is_active': is_active,
                'current_users': len(users_list),
                'current_sources': current_src,
                'current_targets': current_tgt,
                'users_list': users_list
            })
        return result

async def toggle_license_status(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_active FROM licenses WHERE license_key = ?", (license_key,)) as cursor:
            row = await cursor.fetchone()
            if row:
                new_status = 0 if row[0] == 1 else 1
                await db.execute("UPDATE licenses SET is_active = ? WHERE license_key = ?", (new_status, license_key))
                await db.commit()
                return new_status
        return None

async def delete_license(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE active_license = ?", (license_key,)) as cursor:
            users_to_deactivate = [row[0] for row in await cursor.fetchall()]
        
        # آپدیت کاربران
        await db.execute("UPDATE users SET active_license = NULL WHERE active_license = ?", (license_key,))
        
        # حذف آبشاری اطلاعات متصل به این لایسنس
        await db.execute("DELETE FROM licenses WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM subscriptions WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM targets WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM bale_targets WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM eitaa_targets WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM mappings WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM remove_words WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM forbidden_words WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM daily_stats WHERE license_key = ?", (license_key,))
        await db.execute("DELETE FROM post_cache WHERE license_key = ?", (license_key,))
        
        await db.commit()
        return users_to_deactivate

async def update_license_limits(license_key: str, max_users: int, max_sources: int, max_targets: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE licenses 
            SET max_users = ?, max_sources = ?, max_targets = ? 
            WHERE license_key = ?
        """, (max_users, max_sources, max_targets, license_key))
        await db.commit()

# --- توابع کاربران ---
async def check_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT u.name, l.is_active, u.active_license 
            FROM users u 
            LEFT JOIN licenses l ON u.active_license = l.license_key 
            WHERE u.user_id = ?
        """, (user_id,)) as cursor:
            return await cursor.fetchone()

async def use_license(user_id: int, name: str, license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT max_users FROM licenses WHERE license_key = ?", (license_key,)) as cursor:
            row = await cursor.fetchone()
            if not row: return False
            max_users = row[0]

        async with db.execute("SELECT COUNT(*) FROM users WHERE active_license = ?", (license_key,)) as cursor:
            current_users = (await cursor.fetchone())[0]

        async with db.execute("SELECT user_id FROM users WHERE user_id = ? AND active_license = ?", (user_id, license_key)) as cursor:
            already_using = await cursor.fetchone()

        if not already_using and current_users >= max_users:
            return "FULL"

        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as u_cursor:
            if await u_cursor.fetchone():
                await db.execute("UPDATE users SET name = ?, active_license = ? WHERE user_id = ?", (name, license_key, user_id))
            else:
                await db.execute("INSERT INTO users (user_id, name, active_license) VALUES (?, ?, ?)", (user_id, name, license_key))
                
        await db.commit()
        return True

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

async def check_source_limit(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT max_sources FROM licenses WHERE license_key = ?", (license_key,)) as c:
            row = await c.fetchone()
            if not row: return False
            max_s = row[0]
        async with db.execute("SELECT COUNT(*) FROM subscriptions WHERE license_key = ?", (license_key,)) as cursor:
            count = (await cursor.fetchone())[0]
    return count < max_s

async def check_target_limit(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT max_targets FROM licenses WHERE license_key = ?", (license_key,)) as c:
            row = await c.fetchone()
            if not row: return False
            max_t = row[0]
            
        async with db.execute("SELECT COUNT(*) FROM targets WHERE license_key = ?", (license_key,)) as c1:
            t1 = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM bale_targets WHERE license_key = ?", (license_key,)) as c2:
            t2 = (await c2.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM eitaa_targets WHERE license_key = ?", (license_key,)) as c3:
            t3 = (await c3.fetchone())[0]
    return (t1 + t2 + t3) < max_t

# --- توابع کانال مبدأ ---
async def add_subscription(user_id: int, channel_id: int, title: str, username: str = None):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO subscriptions (license_key, channel_id, channel_title, channel_username) VALUES (?, ?, ?, ?)", (lic, channel_id, title, username))
        await db.commit()

async def get_license_subscribers(channel_id: int):
    # برگرداندن لایسنس‌های فعالی که عضو این کانال مبدا هستند
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT s.license_key 
            FROM subscriptions s
            JOIN licenses l ON s.license_key = l.license_key
            WHERE s.channel_id = ? AND l.is_active = 1
        ''', (channel_id,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_users_of_license(license_key: str):
    # برگرداندن کاربران متصل به یک لایسنس برای ارسال پیام دستی (Manual)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE active_license = ?", (license_key,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_channel_title(license_key: str, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_title FROM subscriptions WHERE license_key = ? AND channel_id = ?", (license_key, channel_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "نامشخص"

async def get_user_subscriptions(user_id: int):
    lic = await get_user_license(user_id)
    if not lic: return []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, channel_title, channel_username FROM subscriptions WHERE license_key = ?", (lic,)) as cursor:
            return await cursor.fetchall()

async def delete_subscription_by_id(user_id: int, channel_id: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM mappings WHERE license_key = ? AND source_id = ?", (lic, str(channel_id)))
        await db.execute("DELETE FROM subscriptions WHERE license_key = ? AND CAST(channel_id AS TEXT) = ?", (lic, channel_id))
        await db.commit()

# --- توابع کلمات حذفی و ممنوعه ---
async def add_remove_word(user_id: int, word: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO remove_words (license_key, word) VALUES (?, ?)", (lic, word))
        await db.commit()

async def get_remove_words(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM remove_words WHERE license_key = ?", (license_key,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def delete_remove_word(user_id: int, word: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM remove_words WHERE license_key = ? AND word = ?", (lic, word))
        await db.commit()

async def add_forbidden_word(user_id: int, word: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO forbidden_words (license_key, word) VALUES (?, ?)", (lic, word))
        await db.commit()

async def get_forbidden_words(license_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT word FROM forbidden_words WHERE license_key = ?", (license_key,)) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def delete_forbidden_word(user_id: int, word: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM forbidden_words WHERE license_key = ? AND word = ?", (lic, word))
        await db.commit()

# --- توابع مقاصد تلگرام ---
async def add_target(user_id: int, channel_id: str, append_text: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO targets (license_key, channel_id, append_text) VALUES (?, ?, ?)", (lic, channel_id, append_text))
        await db.commit()

async def get_targets(license_key_or_user_id):
    if isinstance(license_key_or_user_id, int):
        lic = await get_user_license(license_key_or_user_id)
    else:
        lic = license_key_or_user_id
    if not lic: return []
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM targets WHERE license_key = ?", (lic,)) as cursor:
            return await cursor.fetchall()

async def get_target_by_id(license_key: str, channel_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM targets WHERE license_key = ? AND channel_id = ?", (license_key, channel_id)) as cursor:
            return await cursor.fetchone()

async def delete_target(user_id: int, channel_id: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM targets WHERE license_key = ? AND channel_id = ?", (lic, channel_id))
        await db.execute("DELETE FROM mappings WHERE license_key = ? AND target_id = ?", (lic, channel_id))
        await db.commit()

# --- توابع مقاصد بله و ایتا ---
async def add_bale_target(user_id: int, channel_id: str, append_text: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO bale_targets (license_key, channel_id, append_text) VALUES (?, ?, ?)", (lic, channel_id, append_text))
        await db.commit()

async def get_bale_targets(license_key_or_user_id):
    if isinstance(license_key_or_user_id, int):
        lic = await get_user_license(license_key_or_user_id)
    else:
        lic = license_key_or_user_id
    if not lic: return []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM bale_targets WHERE license_key = ?", (lic,)) as cursor:
            return await cursor.fetchall()

async def delete_bale_target(user_id: int, channel_id: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM bale_targets WHERE license_key = ? AND channel_id = ?", (lic, channel_id))
        await db.commit()

async def add_eitaa_target(user_id: int, channel_id: str, append_text: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO eitaa_targets (license_key, channel_id, append_text) VALUES (?, ?, ?)", (lic, channel_id, append_text))
        await db.commit()

async def get_eitaa_targets(license_key_or_user_id):
    if isinstance(license_key_or_user_id, int):
        lic = await get_user_license(license_key_or_user_id)
    else:
        lic = license_key_or_user_id
    if not lic: return []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_id, append_text FROM eitaa_targets WHERE license_key = ?", (lic,)) as cursor:
            return await cursor.fetchall()

async def delete_eitaa_target(user_id: int, channel_id: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM eitaa_targets WHERE license_key = ? AND channel_id = ?", (lic, channel_id))
        await db.commit()

# --- توابع نگاشت کانال‌ها ---
async def set_mapping(user_id: int, source_id: str, target_id: str, mode: str):
    lic = await get_user_license(user_id)
    if not lic: return
    async with aiosqlite.connect(DB_PATH) as db:
        if mode == 'none':
            await db.execute("DELETE FROM mappings WHERE license_key = ? AND source_id = ? AND target_id = ?", (lic, source_id, target_id))
        else:
            await db.execute("INSERT OR REPLACE INTO mappings (license_key, source_id, target_id, mode) VALUES (?, ?, ?, ?)", (lic, source_id, target_id, mode))
        await db.commit()

async def get_mappings(license_key_or_user_id, source_id: str):
    if isinstance(license_key_or_user_id, int):
        lic = await get_user_license(license_key_or_user_id)
    else:
        lic = license_key_or_user_id
    if not lic: return []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT target_id, mode FROM mappings WHERE license_key = ? AND source_id = ?", (lic, str(source_id))) as cursor:
            return await cursor.fetchall()

# --- سیستم کش ---
async def add_to_cache(license_key: str, target_id: str, file_unique_id: str, phash: str, normalized_text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO post_cache (license_key, target_id, file_unique_id, phash, normalized_text, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (license_key, str(target_id), file_unique_id, phash, normalized_text, int(time.time()))
        )
        await db.commit()

async def get_recent_cache(license_key: str, target_id: str):
    three_hours_ago = int(time.time()) - 10800
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT file_unique_id, phash, normalized_text FROM post_cache WHERE timestamp > ? AND license_key = ? AND (target_id = ? OR target_id IS NULL)", 
            (three_hours_ago, license_key, str(target_id))
        ) as cursor:
            return await cursor.fetchall()

async def cleanup_cache():
    three_hours_ago = int(time.time()) - 10800
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM post_cache WHERE timestamp <= ?", (three_hours_ago,))
        await db.commit()
        
async def get_unique_source_channels():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        # فقط از لایسنس‌های فعال واکشی می‌کند
        async with db.execute("""
            SELECT DISTINCT s.channel_id 
            FROM subscriptions s
            JOIN licenses l ON s.license_key = l.license_key
            WHERE l.is_active = 1
        """) as cursor:
            return [row[0] for row in await cursor.fetchall()]

# --- سیستم آمار ---
async def increment_stat(license_key: str, source_id: str, stat_type: str, count: int = 1):
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        await db.execute(f"""
            INSERT INTO daily_stats (license_key, source_id, {stat_type})
            VALUES (?, ?, ?)
            ON CONFLICT(license_key, source_id)
            DO UPDATE SET {stat_type} = {stat_type} + ?
        """, (license_key, str(source_id), count, count))
        await db.commit()

async def get_all_daily_stats():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        async with db.execute("SELECT license_key, source_id, fetched_count, tg_sent_count, bale_sent_count, eitaa_sent_count FROM daily_stats") as cursor:
            return await cursor.fetchall()

async def reset_daily_stats():
    async with aiosqlite.connect(DB_PATH, timeout=20.0) as db:
        await db.execute("DELETE FROM daily_stats")
        await db.commit()