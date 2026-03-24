import uuid
import httpx
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
from telegram.error import BadRequest
from core import bot, LOGGER
from database import *
from channel_reader import client
from telethon.tl.functions.channels import JoinChannelRequest
from core import bot, LOGGER, OWNER_ID

ADMIN_ID = OWNER_ID

# ADMIN_ID = 53718944

(CHOOSING, TYPING_ADD_CHANNEL, TYPING_REMOVE_WORDS, TYPING_FORBIDDEN_WORDS,
 TYPING_TARGET_CHANNEL, TYPING_APPEND_TEXT, 
 ASK_NAME, ASK_LICENSE, WAITING_FOR_EDIT, 
 TYPING_DELETE_TARGET, TYPING_NEW_NAME, TYPING_CHANGE_LICENSE, TYPING_EDIT_SIGNATURE,
 TYPING_BALE_TARGET, TYPING_BALE_APPEND, TYPING_DELETE_BALE, TYPING_EDIT_BALE_SIG,
 TYPING_EITAA_TARGET, TYPING_EITAA_APPEND, TYPING_DELETE_EITAA, TYPING_EDIT_EITAA_SIG, 
 ASK_MAX_USERS, ASK_MAX_SOURCES, ASK_MAX_TARGETS,
 EDIT_LIC_USERS, EDIT_LIC_SOURCES, EDIT_LIC_TARGETS) = range(27)

# --- توابع کیبوردهای داینامیک ---
def get_main_keyboard(user_id):
    # ایتا به کیبورد اصلی اضافه شد
    keys = [["📥 کانال مبدأ"], ["📤 کانال مقصد تلگرام", "🟢 کانال مقصد بله"], ["🟠 کانال مقصد ایتا", "👤 ویرایش پروفایل"]]
    if user_id == ADMIN_ID:
        keys.append(["👑 پنل مدیریت (ویژه ادمین)"])
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

eitaa_keyboard = ReplyKeyboardMarkup([
    ["🎯 فهرست مقصدهای ایتا"],
    ["➕ افزودن مقصد ایتا", "🗑 حذف مقصد ایتا"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

source_keyboard = ReplyKeyboardMarkup([
    ["📋 فهرست کانال‌های مبدأ"],
    ["➕ افزودن کانال مبدأ"],
    ["🚫 تعریف کلمات حذفی", "🗑 فهرست کلمات حذفی"],
    ["⛔️ تعریف کلمات ممنوعه", "🗑 فهرست کلمات ممنوعه"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

target_keyboard = ReplyKeyboardMarkup([
    ["🎯 فهرست کانال‌های مقصد"],
    ["➕ افزودن کانال مقصد", "🗑 حذف کانال مقصد"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

bale_keyboard = ReplyKeyboardMarkup([
    ["🎯 فهرست مقصدهای بله"],
    ["➕ افزودن مقصد بله", "🗑 حذف مقصد بله"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

profile_keyboard = ReplyKeyboardMarkup([
    ["✏️ تغییر نام کاربر", "🔄 تغییر لایسنس"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

admin_keyboard = ReplyKeyboardMarkup([
    ["🔑 تولید لایسنس", "📜 مشاهده لایسنس‌ها"],
    ["بازگشت به منوی اصلی 🔙"]
], resize_keyboard=True)

cancel_keyboard = ReplyKeyboardMarkup([["بازگشت 🔙"]], resize_keyboard=True)

# ----------------- Start & Auth -----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        user = await check_user(user_id)
        if not user:
            import aiosqlite
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("INSERT OR IGNORE INTO users (user_id, name) VALUES (?, ?)", (user_id, "مدیر"))
                await db.commit()
        await update.message.reply_text("سلام مدیر عزیز! 👑", reply_markup=get_main_keyboard(user_id))
        return CHOOSING
    
    user = await check_user(user_id)
    if user:
        if user[1] == 0 and user_id != ADMIN_ID:
            await update.message.reply_text("❌ اعتبار شما پایان یافته است.\nلطفاً لایسنس جدید معتبر خود را وارد کنید:", reply_markup=ReplyKeyboardRemove())
            context.user_data['temp_name'] = user[0]
            return ASK_LICENSE

        await update.message.reply_text(f"سلام {user[0]} عزیز! به پنل مدیریت محتوا خوش آمدید.", reply_markup=get_main_keyboard(user_id))
        return CHOOSING
    
    await update.message.reply_text("👋 سلام! برای استفاده از ربات لطفا نام خود را وارد کنید:")
    return ASK_NAME

async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_name'] = update.message.text
    await update.message.reply_text("🔑 لطفا لایسنس معتبر خود را وارد کنید:")
    return ASK_LICENSE

async def receive_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    license_key = update.message.text
    user_id = update.effective_user.id
    name = context.user_data.get('temp_name', 'کاربر')
    
    success = await use_license(user_id, name, license_key)
    if success == "FULL":
        await update.message.reply_text("❌ ظرفیت مدیران مجاز برای این لایسنس تکمیل شده است.")
        return ASK_LICENSE
    elif success:
        await update.message.reply_text("✅ لایسنس تایید شد! خوش آمدید.", reply_markup=get_main_keyboard(user_id))
        return CHOOSING
    else:
        await update.message.reply_text("❌ لایسنس نامعتبر است یا وجود ندارد. دوباره تلاش کنید:")
        return ASK_LICENSE

async def receive_change_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=profile_keyboard)
        return CHOOSING
    
    success = await change_user_license(user_id, text.strip())
    
    if success == "FULL":
        await update.message.reply_text("❌ ظرفیت مدیران مجاز برای این لایسنس تکمیل شده است.", reply_markup=cancel_keyboard)
        return TYPING_CHANGE_LICENSE
    elif success:
        await update.message.reply_text("✅ لایسنس شما با موفقیت تغییر کرد!", reply_markup=get_main_keyboard(user_id))
        return CHOOSING
    else:
        await update.message.reply_text("❌ لایسنس نامعتبر است یا وجود ندارد. دوباره تلاش کنید:\n(برای لغو «بازگشت 🔙» را بزنید)", reply_markup=cancel_keyboard)
        return TYPING_CHANGE_LICENSE

# ----------------- Main Menu Handlers -----------------
async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # بررسی فعال بودن حساب کاربر
    if user_id != ADMIN_ID:
        user = await check_user(user_id)
        if user and user[1] == 0:
            await update.message.reply_text("❌ اعتبار شما پایان یافته است. لطفا برای وارد کردن لایسنس جدید /start را بزنید.", reply_markup=ReplyKeyboardRemove())
            return CHOOSING

    if text == "📥 کانال مبدأ":
        await update.message.reply_text("تنظیمات کانال‌های مبدأ:", reply_markup=source_keyboard)
        return CHOOSING
    elif text in ["📤 کانال مقصد", "📤 کانال مقصد تلگرام"]:
        await update.message.reply_text("تنظیمات کانال‌های مقصد تلگرام:", reply_markup=target_keyboard)
        return CHOOSING
    elif text == "🟢 کانال مقصد بله":
        await update.message.reply_text("تنظیمات کانال‌های مقصد بله:", reply_markup=bale_keyboard)
        return CHOOSING
    elif text == "🟠 کانال مقصد ایتا":
        await update.message.reply_text("تنظیمات کانال‌های مقصد ایتا:", reply_markup=eitaa_keyboard)
        return CHOOSING
    elif text == "👤 ویرایش پروفایل":
        await update.message.reply_text("بخش پروفایل:", reply_markup=profile_keyboard)
        return CHOOSING
    elif text == "👑 پنل مدیریت (ویژه ادمین)":
        if user_id == ADMIN_ID:
            await update.message.reply_text("پنل ادمین:", reply_markup=admin_keyboard)
        return CHOOSING
    elif text == "بازگشت به منوی اصلی 🔙":
        await update.message.reply_text("به منوی اصلی برگشتیم:", reply_markup=get_main_keyboard(user_id))
        return CHOOSING

    # --- دکمه‌های کانال مبدأ ---
    elif text == "📋 فهرست کانال‌های مبدأ":
        subs = await get_user_subscriptions(user_id)
        if not subs:
            await update.message.reply_text("⚠️ شما هیچ کانال مبدائی ثبت نکرده‌اید!", reply_markup=source_keyboard)
        else:
            await update.message.reply_text("📋 **فهرست کانال‌های مبدأ شما:**", parse_mode='Markdown', reply_markup=source_keyboard)
            for row in subs:
                ch_id, title = row[0], row[1]
                username_str = row[2] if len(row) > 2 and row[2] else str(ch_id)
                msg_txt = f"🔸 {title}\n└ آیدی: {username_str}"
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 حذف کانال", callback_data=f"delsrc_{ch_id}")],
                    [InlineKeyboardButton("🎯 تغییر کانال مقصد", callback_data=f"tgtsrc_{ch_id}")]
                ])
                # آرگومان parse_mode='Markdown' حذف شد
                await update.message.reply_text(msg_txt, reply_markup=markup)
                # --- تا اینجا ---
        return CHOOSING

    elif text == "➕ افزودن کانال مبدأ":
        await update.message.reply_text("آیدی یا یوزرنیم کانال مبدأ رو بفرست (مثلاً @SourceChannel):", reply_markup=cancel_keyboard)
        return TYPING_ADD_CHANNEL

    elif text == "🚫 تعریف کلمات حذفی":
        await update.message.reply_text("کلمه‌ای که می‌خوای از کپشن‌ها حذف بشه رو بفرست:\n(برای خروج «بازگشت 🔙» رو بزن)", reply_markup=cancel_keyboard)
        return TYPING_REMOVE_WORDS

    elif text == "🗑 فهرست کلمات حذفی":
        words = await get_remove_words(user_id)
        if not words:
            await update.message.reply_text("هیچ کلمه‌ای در لیست حذفیات شما وجود ندارد.", reply_markup=source_keyboard)
        else:
            await update.message.reply_text("📋 فهرست کلمات حذفی شما:")
            for w in words:
                keyboard = [[InlineKeyboardButton("🗑 حذف این کلمه", callback_data="delword_action")]]
                await update.message.reply_text(text=w, reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING
    elif text == "⛔️ تعریف کلمات ممنوعه":
        await update.message.reply_text("کلمه‌ای که اگر در پیام بود کل پیام منتشر نشود را بفرستید:\n(برای خروج «بازگشت 🔙» رو بزن)", reply_markup=cancel_keyboard)
        return TYPING_FORBIDDEN_WORDS

    elif text == "🗑 فهرست کلمات ممنوعه":
        from database import get_forbidden_words
        words = await get_forbidden_words(user_id)
        if not words:
            await update.message.reply_text("هیچ کلمه ممنوعه‌ای در لیست شما وجود ندارد.", reply_markup=source_keyboard)
        else:
            await update.message.reply_text("⛔️ فهرست کلمات ممنوعه شما:")
            for w in words:
                keyboard = [[InlineKeyboardButton("🗑 حذف این کلمه", callback_data="delforbid_action")]]
                await update.message.reply_text(text=w, reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING
    # --- دکمه‌های کانال مقصد ایتا ---
    elif text == "🎯 فهرست مقصدهای ایتا":
        targets = await get_eitaa_targets(user_id)
        if not targets:
            await update.message.reply_text("⚠️ شما هنوز کانال مقصد ایتا تنظیم نکرده‌اید!", reply_markup=eitaa_keyboard)
        else:
            await update.message.reply_text("🎯 کانال‌های مقصد ایتا شما:", reply_markup=eitaa_keyboard)
            for ch_id, app_text in targets:
                msg = f"🔸 آیدی ایتا: {ch_id}\n📝 متن امضا:\n{app_text}"
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ ویرایش امضا", callback_data=f"editeitaasig_{ch_id}")],
                    [InlineKeyboardButton("🗑 حذف کانال ایتا", callback_data=f"deleitaatgt_{ch_id}")]
                ])
                await update.message.reply_text(msg, reply_markup=markup)
        return CHOOSING

    elif text == "➕ افزودن مقصد ایتا":
        await update.message.reply_text("آیدی یا شناسه کانال ایتا خودت رو بفرست:", reply_markup=cancel_keyboard)
        return TYPING_EITAA_TARGET

    elif text == "🗑 حذف مقصد ایتا":
        await update.message.reply_text("برای حذف مقصد ایتا، شناسه آن را بفرستید:", reply_markup=cancel_keyboard)
        return TYPING_DELETE_EITAA
# --- دکمه‌های کانال مقصد بله ---
    elif text == "🎯 فهرست مقصدهای بله":
        targets = await get_bale_targets(user_id)
        if not targets:
            await update.message.reply_text("⚠️ شما هنوز کانال مقصد بله تنظیم نکرده‌اید!", reply_markup=bale_keyboard)
        else:
            await update.message.reply_text("🎯 کانال‌های مقصد بله شما:", reply_markup=bale_keyboard)
            for ch_id, app_text in targets:
                msg = f"🔸 آیدی بله: {ch_id}\n📝 متن امضا:\n{app_text}"
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ ویرایش امضا", callback_data=f"editbalesig_{ch_id}")],
                    [InlineKeyboardButton("🗑 حذف کانال بله", callback_data=f"delbaletgt_{ch_id}")]
                ])
                await update.message.reply_text(msg, reply_markup=markup)
        return CHOOSING

    elif text == "➕ افزودن مقصد بله":
        await update.message.reply_text("آیدی یا شناسه کانال بله خودت رو بفرست:", reply_markup=cancel_keyboard)
        return TYPING_BALE_TARGET

    elif text == "🗑 حذف مقصد بله":
        await update.message.reply_text("برای حذف مقصد بله، شناسه آن را بفرستید:", reply_markup=cancel_keyboard)
        return TYPING_DELETE_BALE
    # --- دکمه‌های کانال مقصد ---
    elif text == "🎯 فهرست کانال‌های مقصد":
        targets = await get_targets(user_id)
        if not targets:
            await update.message.reply_text("⚠️ شما هنوز کانال مقصدی تنظیم نکرده‌اید!", reply_markup=target_keyboard)
        else:
            await update.message.reply_text("🎯 کانال‌های مقصد شما:", reply_markup=target_keyboard)
            for ch_id, app_text in targets:
                # اینجا فرمت‌ها رو برداشتیم تا کاراکترهای خاصِ امضا باعث کرش نشن
                msg = f"🔸 آیدی: {ch_id}\n📝 متن امضا:\n{app_text}"
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ ویرایش امضا", callback_data=f"editsig_{ch_id}")],
                    [InlineKeyboardButton("🗑 حذف کانال", callback_data=f"deltgt_{ch_id}")]
                ])
                # حذف parse_mode از اینجا برای جلوگیری از ارور
                await update.message.reply_text(msg, reply_markup=markup)
        return CHOOSING

    elif text == "➕ افزودن کانال مقصد":
        await update.message.reply_text("آیدی کانال شخصی خودت رو بفرست (ربات @groupmanager2026_bot ادمین اونجا باشه):", reply_markup=cancel_keyboard)
        return TYPING_TARGET_CHANNEL

    elif text == "🗑 حذف کانال مقصد":
        await update.message.reply_text("برای حذف کانال مقصد خود، آیدی آن را بفرستید:", reply_markup=cancel_keyboard)
        return TYPING_DELETE_TARGET

    # --- دکمه‌های پروفایل ---
    elif text == "✏️ تغییر نام کاربر":
        await update.message.reply_text("نام جدید خود را وارد کنید:", reply_markup=cancel_keyboard)
        return TYPING_NEW_NAME

    elif text == "🔄 تغییر لایسنس":
        await update.message.reply_text("🔑 لطفاً لایسنس جدید خود را وارد کنید:\n(برای لغو «بازگشت 🔙» را بزنید)", reply_markup=cancel_keyboard)
        return TYPING_CHANGE_LICENSE

# --- دکمه‌های پنل ادمین ---
    elif text == "🔑 تولید لایسنس" and user_id == ADMIN_ID:
        await update.message.reply_text("چند نفر مدیر می‌توانند از این لایسنس استفاده کنند؟ (فقط یک عدد وارد کنید):", reply_markup=cancel_keyboard)
        return ASK_MAX_USERS

    elif text == "📜 مشاهده لایسنس‌ها" and user_id == ADMIN_ID:
        licenses = await get_all_licenses()
        if not licenses:
            await update.message.reply_text("هیچ لایسنسی یافت نشد.")
            return CHOOSING
            
        chunk_text = "📜 **لیست لایسنس‌ها:**\n\n"
        chunk_keys = []
        count = 0
        
        for lic in licenses:
            lic_key = lic[0]
            status = f"استفاده شده توسط {lic[3]} (آیدی: {lic[2]})" if lic[1] else "آزاد"
            
            m_users = lic[4] if len(lic) > 4 and lic[4] is not None else 1
            m_src = lic[5] if len(lic) > 5 and lic[5] is not None else 1000
            m_tgt = lic[6] if len(lic) > 6 and lic[6] is not None else 1000
            
            chunk_text += f"🔑 `{lic_key}`\n"
            chunk_text += f"وضعیت: {status}\n"
            chunk_text += f"ظرفیت: {m_users} کاربر | {m_src} مبدأ | {m_tgt} مقصد\n\n"
            
            # دکمه‌های شیشه‌ای مخصوص همین لایسنس
            chunk_keys.append([
                InlineKeyboardButton(f"✏️ ویرایش ظرفیت", callback_data=f"editlic_{lic_key}"),
                InlineKeyboardButton(f"🗑 حذف لایسنس", callback_data=f"dellic_{lic_key}")
            ])
            
            count += 1
            if count % 5 == 0: # ارسال هر 5 لایسنس در یک پیام برای تمیزی ظاهر
                await update.message.reply_text(chunk_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(chunk_keys))
                chunk_text = ""
                chunk_keys = []
                
        if chunk_text:
            await update.message.reply_text(chunk_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(chunk_keys))
            
        return CHOOSING

async def receive_max_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط یک عدد وارد کنید:")
        return ASK_MAX_USERS
    context.user_data['max_users'] = int(text)
    await update.message.reply_text("حداکثر چند کانال مبدأ می‌تواند ثبت کند؟ (عدد)")
    return ASK_MAX_SOURCES

async def receive_max_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return ASK_MAX_SOURCES
    context.user_data['max_sources'] = int(text)
    await update.message.reply_text("حداکثر چند کانال مقصد (تلگرام و بله) می‌تواند ثبت کند؟ (عدد)")
    return ASK_MAX_TARGETS

async def receive_max_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return ASK_MAX_TARGETS
    
    max_targets = int(text)
    max_users = context.user_data.get('max_users', 1)
    max_sources = context.user_data.get('max_sources', 100)
    
    new_license = "LIC-" + str(uuid.uuid4()).split("-")[0].upper()
    await add_advanced_license(new_license, max_users, max_sources, max_targets)
    
    msg = (f"✅ لایسنس جدید تولید شد:\n`{new_license}`\n\n"
           f"👥 ظرفیت مدیران: {max_users} نفر\n"
           f"📥 ظرفیت مبدأ: {max_sources} کانال\n"
           f"📤 ظرفیت مقصد: {max_targets} کانال")
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=admin_keyboard)
    return CHOOSING

# ----------------- Input Receivers -----------------
async def receive_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING

    owner_id = await get_owner(update.effective_user.id)
    if not await check_source_limit(owner_id):
        await update.message.reply_text("❌ سقف مجاز کانال‌های مبدأ برای لایسنس شما پر شده است!", reply_markup=source_keyboard)
        return CHOOSING
        
    wait_msg = await update.message.reply_text("⏳ در حال بررسی...")
    try:
        entity = await client.get_entity(text)
        await client(JoinChannelRequest(entity))
        channel_id = entity.id
        bot_api_chat_id = int(f"-100{channel_id}") if not str(channel_id).startswith("-100") else channel_id
        
        username = f"@{entity.username}" if getattr(entity, 'username', None) else text
        await add_subscription(update.effective_user.id, bot_api_chat_id, entity.title, username)
        
        await wait_msg.delete()
        await update.message.reply_text(f"✅ کانال «{entity.title}» ثبت شد.", reply_markup=source_keyboard)
        return CHOOSING
    except Exception as e:
        LOGGER.error(f"Error joining channel: {e}")
        await wait_msg.delete()
        await update.message.reply_text(f"❌ خطا!\n{e}\nدوباره تلاش کنید یا برگردید.", reply_markup=cancel_keyboard)
        return TYPING_ADD_CHANNEL

async def receive_remove_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("✅ خروج از بخش کلمات.", reply_markup=source_keyboard)
        return CHOOSING
    await add_remove_word(update.effective_user.id, text)
    await update.message.reply_text(f"🗑 کلمه «{text}» اضافه شد. کلمه بعدی را بفرستید یا برگردید:", reply_markup=cancel_keyboard)
    return TYPING_REMOVE_WORDS

async def receive_target_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=target_keyboard)
        return CHOOSING
    
    owner_id = await get_owner(update.effective_user.id)
    
    if not await check_target_limit(owner_id):
        await update.message.reply_text("❌ سقف مجاز کانال‌های مقصد برای لایسنس شما پر شده است!\nنمی‌توانید کانال جدیدی اضافه کنید.", reply_markup=target_keyboard)
        return CHOOSING

    context.user_data['temp_target'] = text
    await update.message.reply_text("✅ حالا متنی که می‌خوای به انتهای پیام‌ها اضافه بشه رو بفرست:\n(برای لغو «بازگشت 🔙» را بزن)", reply_markup=cancel_keyboard)
    return TYPING_APPEND_TEXT

async def receive_eitaa_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=eitaa_keyboard)
        return CHOOSING
    
    owner_id = await get_owner(update.effective_user.id)
    if not await check_target_limit(owner_id):
        await update.message.reply_text("❌ سقف مجاز پر شده است!", reply_markup=eitaa_keyboard)
        return CHOOSING

    context.user_data['temp_eitaa_target'] = text
    await update.message.reply_text("✅ حالا متنی که می‌خوای به انتهای پیام‌ها تو ایتا اضافه بشه رو بفرست:\n(برای لغو «بازگشت 🔙» را بزن)", reply_markup=cancel_keyboard)
    return TYPING_EITAA_APPEND

async def receive_eitaa_append(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=eitaa_keyboard)
        return CHOOSING
    await add_eitaa_target(update.effective_user.id, context.user_data['temp_eitaa_target'], update.message.text)
    await update.message.reply_text("✅ کانال مقصد ایتا و امضا ذخیره شد. توجه داشته باشید حتما باید اکانت @masoudfa88 به عنوان مدیر کانال تعریف شده باشد!", reply_markup=eitaa_keyboard)
    return CHOOSING

async def receive_delete_eitaa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=eitaa_keyboard)
        return CHOOSING
    await delete_eitaa_target(update.effective_user.id, text.strip())
    await update.message.reply_text("✅ در صورتی که کانال در لیست مقصدها بود، حذف شد.", reply_markup=eitaa_keyboard)
    return CHOOSING

async def receive_edit_eitaa_signature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "بازگشت 🔙":
        await update.message.reply_text("عملیات لغو شد.", reply_markup=eitaa_keyboard)
        return CHOOSING
    ch_id = context.user_data.get('edit_sig_eitaa_target')
    if ch_id:
        await add_eitaa_target(user_id, ch_id, text)
        await update.message.reply_text("✅ امضا با موفقیت به‌روزرسانی شد!", reply_markup=eitaa_keyboard)
    return CHOOSING

async def receive_bale_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=bale_keyboard)
        return CHOOSING
    
    owner_id = await get_owner(update.effective_user.id)
    
    if not await check_target_limit(owner_id):
        await update.message.reply_text("❌ سقف مجاز کانال‌های مقصد برای لایسنس شما پر شده است!\nنمی‌توانید مقصد بله جدیدی اضافه کنید.", reply_markup=bale_keyboard)
        return CHOOSING

    context.user_data['temp_bale_target'] = text
    await update.message.reply_text("✅ حالا متنی که می‌خوای به انتهای پیام‌ها تو بله اضافه بشه رو بفرست:\n(برای لغو «بازگشت 🔙» را بزن)", reply_markup=cancel_keyboard)
    return TYPING_BALE_APPEND

async def receive_append_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=target_keyboard)
        return CHOOSING
    await add_target(update.effective_user.id, context.user_data['temp_target'], update.message.text)
    await update.message.reply_text("✅ کانال مقصد و امضا ذخیره شد!", reply_markup=target_keyboard)
    return CHOOSING

async def receive_delete_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=target_keyboard)
        return CHOOSING
    
    await delete_target(update.effective_user.id, text.strip())
    await update.message.reply_text(f"✅ در صورتی که کانال در لیست مقصدها بود، حذف شد.", reply_markup=target_keyboard)
    return CHOOSING

async def receive_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=profile_keyboard)
        return CHOOSING
    
    await update_user_name(update.effective_user.id, text.strip())
    await update.message.reply_text(f"✅ نام شما به «{text}» تغییر یافت.", reply_markup=profile_keyboard)
    return CHOOSING

async def receive_bale_append(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=bale_keyboard)
        return CHOOSING
    await add_bale_target(update.effective_user.id, context.user_data['temp_bale_target'], update.message.text)
    await update.message.reply_text("✅ کانال مقصد بله و امضا ذخیره شد. توجه داشته باشید ربات @channelmanager2026_bot را حتما به عنوان مدیر کانال تعریف نمایید.!", reply_markup=bale_keyboard)
    return CHOOSING

async def receive_delete_bale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("لغو شد.", reply_markup=bale_keyboard)
        return CHOOSING
    await delete_bale_target(update.effective_user.id, text.strip())
    await update.message.reply_text(f"✅ در صورتی که کانال در لیست مقصدها بود، حذف شد.", reply_markup=bale_keyboard)
    return CHOOSING

async def receive_edit_bale_signature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "بازگشت 🔙":
        await update.message.reply_text("عملیات لغو شد.", reply_markup=bale_keyboard)
        return CHOOSING
    
    ch_id = context.user_data.get('edit_sig_bale_target')
    if ch_id:
        await add_bale_target(user_id, ch_id, text)
        await update.message.reply_text("✅ امضا با موفقیت به‌روزرسانی شد!", reply_markup=bale_keyboard)
    context.user_data.pop('edit_sig_bale_target', None)
    return CHOOSING

# ----------------- Inline Buttons (Publish / Edit) -----------------
async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        user = await check_user(user_id)
        if user and user[1] == 0:
            await query.answer("❌ اعتبار شما پایان یافته است!", show_alert=True)
            return
            
    if data == "ignore":
        await query.answer()
        return
    if data == "delforbid_action":
        from database import delete_forbidden_word
        word_to_delete = query.message.text
        await delete_forbidden_word(user_id, word_to_delete)
        await query.answer("✅ کلمه ممنوعه حذف شد.")
        await query.edit_message_text(f"✅ کلمه ممنوعه زیر حذف شد:\n\n{word_to_delete}")
        return
    if data.startswith("delsrc_"):
        ch_id = data.split("_")[1]
        await delete_subscription_by_id(user_id, ch_id)
        await query.answer("✅ کانال مبدأ و تنظیماتش حذف شد.")
        await query.message.delete()
        return

    if data == "delword_action":
        # گرفتن کلمه از روی متن پیامی که دکمه زیر آن قرار دارد
        word_to_delete = query.message.text
        
        await delete_remove_word(user_id, word_to_delete)
        await query.answer("✅ کلمه حذف شد.")
        
        # تغییر متن پیام به حالت حذف شده
        await query.edit_message_text(f"✅ کلمه زیر با موفقیت حذف شد:\n\n{word_to_delete}")
        return
    
    if data.startswith("tgtsrc_"):
        src_id = data.split("_")[1]
        targets = await get_targets(user_id)
        if not targets:
            await query.answer("هیچ کانال مقصدی تنظیم نکرده‌اید!", show_alert=True)
            return
        
        mappings = await get_mappings(user_id, src_id)
        map_dict = {m[0]: m[1] for m in mappings}

        keys = []
        for tgt_id, _ in targets:
            mode = map_dict.get(tgt_id, 'none')
            btn_auto = "🟢 خودکار (فعال)" if mode == 'auto' else "خودکار"
            btn_manual = "🟡 با تایید (فعال)" if mode == 'manual' else "با تایید"
            
            keys.append([InlineKeyboardButton(f"🎯 به مقصد: {tgt_id}", callback_data="ignore")])
            keys.append([
                InlineKeyboardButton(btn_auto, callback_data=f"setmap_auto_{src_id}_{tgt_id}"),
                InlineKeyboardButton(btn_manual, callback_data=f"setmap_manual_{src_id}_{tgt_id}"),
                InlineKeyboardButton("حذف از انتشار", callback_data=f"setmap_none_{src_id}_{tgt_id}")
            ])
        keys.append([InlineKeyboardButton("بستن منو ❌", callback_data="close_menu")])
        
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keys))
        return

    if data.startswith("setmap_"):
        parts = data.split("_", 3)
        mode, src_id, tgt_id = parts[1], parts[2], parts[3]
        
        await set_mapping(user_id, src_id, tgt_id, mode)
        await query.answer("✅ وضعیت انتشار ثبت شد.")
        
        targets = await get_targets(user_id)
        mappings = await get_mappings(user_id, src_id)
        map_dict = {m[0]: m[1] for m in mappings}
        keys = []
        for tid, _ in targets:
            cmode = map_dict.get(tid, 'none')
            btn_auto = "🟢 خودکار (فعال)" if cmode == 'auto' else "خودکار"
            btn_manual = "🟡 با تایید (فعال)" if cmode == 'manual' else "با تایید"
            
            keys.append([InlineKeyboardButton(f"🎯 به مقصد: {tid}", callback_data="ignore")])
            keys.append([
                InlineKeyboardButton(btn_auto, callback_data=f"setmap_auto_{src_id}_{tid}"),
                InlineKeyboardButton(btn_manual, callback_data=f"setmap_manual_{src_id}_{tid}"),
                InlineKeyboardButton("حذف از انتشار", callback_data=f"setmap_none_{src_id}_{tid}")
            ])
        keys.append([InlineKeyboardButton("بستن منو ❌", callback_data="close_menu")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keys))
        return

    if data == "close_menu":
        await query.message.delete()
        return

    msg_id = query.message.message_id
    
    if data.startswith("pub_sgl_"):
        src_id = data.split("_")[2]
        mappings = await get_mappings(user_id, src_id)
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']
        
        if not manual_targets:
            await query.answer("مقصدی برای انتشار دستی تنظیم نشده!", show_alert=True)
            return

        original_text = query.message.text or query.message.caption or ""
        
        for tgt in manual_targets:
            target_info = await get_target_by_id(user_id, tgt)
            if not target_info: continue
            append_text = target_info[1]
            final_text = f"{original_text}\n\n{append_text}" if original_text else append_text
            
            if query.message.text: 
                await context.bot.send_message(chat_id=tgt, text=final_text)
            else: 
                await context.bot.copy_message(chat_id=tgt, from_chat_id=user_id, message_id=msg_id, caption=final_text)
        
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ پیام در کانال‌های مقصد تأییدشده منتشر شد.")

    elif data.startswith("pub_alb_"):
        parts = data.split("_")
        start_id = int(parts[2])
        end_id = int(parts[3])
        src_id = parts[4]
        
        mappings = await get_mappings(user_id, src_id)
        manual_targets = [m[0] for m in mappings if m[1] == 'manual']
        if not manual_targets:
            await query.answer("مقصدی برای انتشار دستی تنظیم نشده!", show_alert=True)
            return

        # 🔥 تغییر مهم: استفاده از pop برای پاک کردن از رم
        original_caption = ALBUM_CAPTIONS.pop(start_id, "")
        
        for tgt in manual_targets:
            target_info = await get_target_by_id(user_id, tgt)
            if not target_info: continue
            append_text = target_info[1]
            final_text = f"{original_caption}\n\n{append_text}" if original_caption else append_text

            try:
                await context.bot.edit_message_caption(chat_id=user_id, message_id=start_id, caption=final_text)
            except BadRequest:
                pass

            async with httpx.AsyncClient() as http_client:
                await http_client.post(
                    f"https://api.telegram.org/bot{context.bot.token}/copyMessages",
                    json={
                        "chat_id": tgt,
                        "from_chat_id": user_id,
                        "message_ids": list(range(start_id, end_id + 1))
                    }
                )

        try:
            await context.bot.edit_message_caption(chat_id=user_id, message_id=start_id, caption=original_caption)
        except:
            pass

        await query.edit_message_text("✅ آلبوم در مقصدهای تأییدشده منتشر شد.")

    elif data.startswith("edit_sgl_"):
        src_id = data.split("_")[2]
        context.user_data['editing_data'] = {'type': 'sgl', 'msg_id': msg_id, 'src_id': src_id}
        original_text = query.message.text or query.message.caption or ""
        
        await query.message.reply_text(
            f"متن فعلی پیام:\n\n{original_text}\n\n👇 **لطفا کپشن جدید را بفرستید:**\n(برای انصراف «بازگشت 🔙» را بفرستید)",
            reply_markup=cancel_keyboard,
            parse_mode='Markdown'
        )
        return WAITING_FOR_EDIT

    elif data.startswith("edit_alb_"):
        parts = data.split("_")
        src_id = parts[4]
        context.user_data['editing_data'] = {'type': 'alb', 'start_id': int(parts[2]), 'end_id': int(parts[3]), 'src_id': src_id}
        original_text = ALBUM_CAPTIONS.get(int(parts[2]), "")

        await query.message.reply_text(
            f"متن فعلی آلبوم:\n\n{original_text}\n\n👇 **لطفا کپشن جدید را بفرستید:**\n(برای انصراف «بازگشت 🔙» را بفرستید)",
            reply_markup=cancel_keyboard,
            parse_mode='Markdown'
        )
        return WAITING_FOR_EDIT

async def receive_edited_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_text = update.message.text
    user_id = update.effective_user.id
    edit_data = context.user_data.get('editing_data')
    
    if new_text == "بازگشت 🔙":
        await update.message.reply_text("عملیات ویرایش لغو شد.", reply_markup=get_main_keyboard(user_id))
        return CHOOSING

    if not edit_data:
        await update.message.reply_text("خطا در سیستم. دوباره تلاش کنید.", reply_markup=get_main_keyboard(user_id))
        return CHOOSING

    src_id = edit_data['src_id']
    mappings = await get_mappings(user_id, src_id)
    manual_targets = [m[0] for m in mappings if m[1] == 'manual']

    if not manual_targets:
        await update.message.reply_text("مقصدی برای انتشار دستی یافت نشد!", reply_markup=get_main_keyboard(user_id))
        return CHOOSING

    try:
        if edit_data['type'] == 'sgl':
            msg_id = edit_data['msg_id']
            for tgt in manual_targets:
                target_info = await get_target_by_id(user_id, tgt)
                if not target_info: continue
                app_text = target_info[1]
                final_text = f"{new_text}\n\n{app_text}"
                try:
                    await context.bot.copy_message(chat_id=tgt, from_chat_id=user_id, message_id=msg_id, caption=final_text)
                except BadRequest as e:
                    if "Message to copy not found" in str(e) or "Caption can't be edited" in str(e):
                        await context.bot.send_message(chat_id=tgt, text=final_text)
            
            await update.message.reply_text("✅ پیام با کپشن جدید در مقصدها منتشر شد!", reply_markup=get_main_keyboard(user_id))

        elif edit_data['type'] == 'alb':
            start_id = edit_data['start_id']
            end_id = edit_data['end_id']
            
            for tgt in manual_targets:
                target_info = await get_target_by_id(user_id, tgt)
                if not target_info: continue
                app_text = target_info[1]
                final_text = f"{new_text}\n\n{app_text}"

                try:
                    await context.bot.edit_message_caption(chat_id=user_id, message_id=start_id, caption=final_text)
                except:
                    pass

                async with httpx.AsyncClient() as http_client:
                    await http_client.post(
                        f"https://api.telegram.org/bot{context.bot.token}/copyMessages",
                        json={
                            "chat_id": tgt,
                            "from_chat_id": user_id,
                            "message_ids": list(range(start_id, end_id + 1))
                        }
                    )
            
            try:
                await context.bot.edit_message_caption(chat_id=user_id, message_id=start_id, caption=new_text)
            except:
                pass
                
            ALBUM_CAPTIONS.pop(start_id, None)
            await update.message.reply_text("✅ آلبوم با کپشن جدید در مقصدها منتشر شد!", reply_markup=get_main_keyboard(user_id))

    except Exception as e:
        await update.message.reply_text(f"❌ خطا در ارسال! {e}", reply_markup=get_main_keyboard(user_id))
    
    context.user_data.pop('editing_data', None)
    return CHOOSING

async def target_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("editsig_"):
        ch_id = data.split("_")[1]
        context.user_data['edit_sig_target'] = ch_id
        await query.answer()
        await query.message.reply_text(
            f"✏️ لطفا امضای جدید برای کانال `{ch_id}` را بفرستید:\n(برای انصراف «بازگشت 🔙» را بزنید)",
            reply_markup=cancel_keyboard,
            parse_mode='Markdown'
        )
        return TYPING_EDIT_SIGNATURE
        
    elif data.startswith("deltgt_"):
        ch_id = data.split("_")[1]
        await delete_target(user_id, ch_id)
        await query.answer("✅ کانال مقصد حذف شد.")
        await query.message.delete()
        return CHOOSING
    elif data.startswith("editbalesig_"):
        ch_id = data.split("_")[1]
        context.user_data['edit_sig_bale_target'] = ch_id
        await query.answer()
        await query.message.reply_text(f"✏️ لطفا امضای جدید برای کانال بله `{ch_id}` را بفرستید:\n(برای انصراف «بازگشت 🔙» را بزنید)", reply_markup=cancel_keyboard, parse_mode='Markdown')
        return TYPING_EDIT_BALE_SIG
    elif data.startswith("editeitaasig_"):
        ch_id = data.split("_")[1]
        context.user_data['edit_sig_eitaa_target'] = ch_id
        await query.answer()
        await query.message.reply_text(f"✏️ لطفا امضای جدید برای کانال ایتا `{ch_id}` را بفرستید:\n(برای انصراف «بازگشت 🔙» را بزنید)", reply_markup=cancel_keyboard, parse_mode='Markdown')
        return TYPING_EDIT_EITAA_SIG
        
    elif data.startswith("deleitaatgt_"):
        ch_id = data.split("_")[1]
        await delete_eitaa_target(user_id, ch_id)
        await query.answer("✅ کانال مقصد ایتا حذف شد.")
        await query.message.delete()
        return CHOOSING
        
    elif data.startswith("delbaletgt_"):
        ch_id = data.split("_")[1]
        await delete_bale_target(user_id, ch_id)
        await query.answer("✅ کانال مقصد بله حذف شد.")
        await query.message.delete()
        return CHOOSING

async def receive_edit_signature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "بازگشت 🔙":
        await update.message.reply_text("عملیات لغو شد.", reply_markup=target_keyboard)
        return CHOOSING
    
    ch_id = context.user_data.get('edit_sig_target')
    if not ch_id:
        await update.message.reply_text("خطا! کانال یافت نشد.", reply_markup=target_keyboard)
        return CHOOSING
        
    await add_target(user_id, ch_id, text)
    await update.message.reply_text("✅ امضا با موفقیت به‌روزرسانی شد!", reply_markup=target_keyboard)
    context.user_data.pop('edit_sig_target', None)
    return CHOOSING

async def admin_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data.startswith("editlic_"):
        lic_key = data.split("_")[1]
        context.user_data['edit_lic_key'] = lic_key
        await query.answer()
        await query.message.reply_text(
            f"✏️ در حال ویرایش ظرفیت لایسنس `{lic_key}`\n\nتعداد **کاربران مدیر** مجاز را وارد کنید:\n(برای لغو «بازگشت 🔙» را بزنید)", 
            reply_markup=cancel_keyboard, parse_mode='Markdown'
        )
        return EDIT_LIC_USERS
        
    elif data.startswith("dellic_"):
        lic_key = data.split("_")[1]
        users_revoked = await delete_license(lic_key) # دریافت لیست کل کاربران
        await query.answer("✅ لایسنس حذف شد.", show_alert=True)
        
        try:
            await query.edit_message_text(f"🗑 لایسنس `{lic_key}` با موفقیت حذف شد.", parse_mode='Markdown')
        except: pass
        
        # ارسال پیام اتمام اعتبار برای همه مدیران متصل به این لایسنس
        if users_revoked:
            for uid in users_revoked:
                try:
                    await context.bot.send_message(
                        chat_id=uid, 
                        text="❌ اعتبار شما پایان یافت.\nربات برای شما غیرفعال شد. لطفا برای وارد کردن لایسنس جدید /start را بزنید.", 
                        reply_markup=ReplyKeyboardRemove()
                    )
                except: pass
        return CHOOSING

async def receive_forbidden_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙":
        await update.message.reply_text("✅ خروج از بخش کلمات ممنوعه.", reply_markup=source_keyboard)
        return CHOOSING
    from database import add_forbidden_word
    await add_forbidden_word(update.effective_user.id, text)
    await update.message.reply_text(f"⛔️ کلمه «{text}» به لیست ممنوعه اضافه شد. کلمه بعدی را بفرستید یا برگردید:", reply_markup=cancel_keyboard)
    return TYPING_FORBIDDEN_WORDS

# توابع دریافت مقادیر ویرایش
async def receive_edit_lic_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط یک عدد وارد کنید:")
        return EDIT_LIC_USERS
    context.user_data['edit_max_users'] = int(text)
    await update.message.reply_text("حداکثر چند کانال مبدأ می‌تواند ثبت کند؟ (عدد)")
    return EDIT_LIC_SOURCES

async def receive_edit_lic_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return EDIT_LIC_SOURCES
    context.user_data['edit_max_sources'] = int(text)
    await update.message.reply_text("حداکثر چند کانال مقصد (تلگرام و بله) می‌تواند ثبت کند؟ (عدد)")
    return EDIT_LIC_TARGETS

async def receive_edit_lic_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بازگشت 🔙": return CHOOSING
    if not text.isdigit():
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return EDIT_LIC_TARGETS
    
    max_targets = int(text)
    max_users = context.user_data.get('edit_max_users', 1)
    max_sources = context.user_data.get('edit_max_sources', 100)
    lic_key = context.user_data.get('edit_lic_key')
    
    if lic_key:
        await update_license_limits(lic_key, max_users, max_sources, max_targets)
        msg = (f"✅ لایسنس `{lic_key}` با موفقیت ویرایش شد:\n\n"
               f"👥 ظرفیت مدیران: {max_users} نفر\n"
               f"📥 ظرفیت مبدأ: {max_sources} کانال\n"
               f"📤 ظرفیت مقصد: {max_targets} کانال")
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=admin_keyboard)
    else:
        await update.message.reply_text("❌ خطا در یافتن لایسنس.", reply_markup=admin_keyboard)
        
    return CHOOSING

# ساخت هندلر مکالمه
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler("start", start_cmd),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choice)
    ],
    states={
        CHOOSING: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_choice),
            CallbackQueryHandler(target_inline_callback, pattern="^(editsig_|deltgt_|editbalesig_|delbaletgt_|editeitaasig_|deleitaatgt_)"),
            CallbackQueryHandler(admin_inline_callback, pattern="^(editlic_|dellic_)")
        ],
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
        ASK_LICENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_license)],
        TYPING_ADD_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_add_channel)],
        TYPING_REMOVE_WORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_remove_words)],
        TYPING_TARGET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_channel)],
        TYPING_APPEND_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_append_text)],
        TYPING_DELETE_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_target)],
        TYPING_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_name)],
        TYPING_CHANGE_LICENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_change_license)],
        WAITING_FOR_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edited_caption)],
        TYPING_EDIT_SIGNATURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_signature)],
        TYPING_BALE_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bale_target)],
        TYPING_BALE_APPEND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bale_append)],
        TYPING_DELETE_BALE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_bale)],
        TYPING_EDIT_BALE_SIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_bale_signature)],
        TYPING_EITAA_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_eitaa_target)],
        TYPING_EITAA_APPEND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_eitaa_append)],
        TYPING_DELETE_EITAA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_eitaa)],
        TYPING_EDIT_EITAA_SIG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_eitaa_signature)],
        TYPING_FORBIDDEN_WORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_forbidden_words)],
        ASK_MAX_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_max_users)],
        ASK_MAX_SOURCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_max_sources)],
        ASK_MAX_TARGETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_max_targets)],
        EDIT_LIC_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_lic_users)],
        EDIT_LIC_SOURCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_lic_sources)],
        EDIT_LIC_TARGETS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_lic_targets)],
    },
    fallbacks=[CommandHandler("start", start_cmd)]
)

bot.add_handler(conv_handler)
bot.add_handler(CallbackQueryHandler(inline_callback, pattern="^(pub_|edit_|ignore|delsrc_|tgtsrc_|setmap_|deltgt_|delbaletgt_|editbalesig_|close_menu|delword_|delforbid_action)"))