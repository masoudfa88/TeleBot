import asyncio
import logging
import datetime  # 👈 اضافه شد

def run() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    from core import bot, LOGGER
    # 👈 توابع جدید دیتابیس اینجا ایمپورت شدند
    from database import init_db, get_all_daily_stats, reset_daily_stats, get_channel_title 
    import channel_reader
    import default
    import misc

    async def start_services():
        LOGGER.info("⏳ Setting up services and checking connection to Telegram...")
        
        await init_db()
        
        try:
            await bot.initialize()
            me_bot = await bot.bot.get_me()
            LOGGER.info(f"✅ Successful ping: The robot has established communication with the server. (@{me_bot.username})")
            
            await bot.start()
            await bot.updater.start_polling()
            LOGGER.info("▶️ The robot is receiving messages....")
        except Exception as e:
            LOGGER.error(f"❌ Robot connection failed! Check your proxy or internet. Error: {e}")
            return  

        async def daily_report_task():
            LOGGER.info("📅 سیستم گزارش‌گیری روزانه (ساعت 12 شب) فعال شد.")
            while True:
                now = datetime.datetime.now()
                # پیدا کردن زمان دقیق 12 شب امشب (بامداد فردا)
                tomorrow = now + datetime.timedelta(days=1)
                midnight = datetime.datetime(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day, hour=0, minute=0, second=0)
                seconds_until_midnight = (midnight - now).total_seconds()

                LOGGER.info(f"⏳ گزارش بعدی {seconds_until_midnight / 3600:.1f} ساعت دیگر ارسال می‌شود.")
                await asyncio.sleep(seconds_until_midnight)

                try:
                    stats = await get_all_daily_stats()
                    if stats:
                        user_reports = {}
                        for user_id, source_id, fetched, tg_sent, bale_sent, eitaa_sent in stats:
                            if user_id not in user_reports:
                                user_reports[user_id] = []

                            # نام کانال مبدأ
                            ch_id_int = int(source_id) if source_id.lstrip('-').isdigit() else source_id
                            ch_title = await get_channel_title(user_id, ch_id_int)

                            report_line = (
                                f"📢 **{ch_title}** (`{source_id}`)\n"
                                f"📥 پیام‌های بررسی شده: {fetched}\n"
                                f"✈️ منتشر شده در تلگرام: {tg_sent}\n"
                                f"🟢 منتشر شده در بله: {bale_sent}\n"
                                f"🟠 منتشر شده در ایتا: {eitaa_sent}\n"
                            )
                            user_reports[user_id].append(report_line)

                        for uid, lines in user_reports.items():
                            report_text = "📊 **گزارش عملکرد امروز ربات:**\n\n" + "\n\n".join(lines)
                            try:
                                await bot.bot.send_message(chat_id=uid, text=report_text, parse_mode='Markdown')
                            except Exception as e:
                                LOGGER.error(f"❌ خطا در ارسال گزارش برای کاربر {uid}: {e}")

                    # ریست کردن جدول برای روز بعد
                    await reset_daily_stats()
                    LOGGER.info("✅ گزارش‌های روزانه با موفقیت ارسال و آمار ریست شد.")
                except Exception as e:
                    LOGGER.error(f"❌ خطا در چرخه گزارش روزانه: {e}")
        
        # 👈 اضافه کردن این تسک به چرخه‌ی پس‌زمینه (مکان درست اینجاست)
        asyncio.create_task(daily_report_task())

        try:
            # راه‌اندازی کلاینت دوم در محیط امن
            await channel_reader.main()
        except asyncio.CancelledError:
            LOGGER.info("🛑 Shutting down gracefully...")
        finally:
            # خاموش کردن کامل بات برای جلوگیری از تداخل Loop
            if bot.updater and bot.updater.running:
                await bot.updater.stop()
            await bot.stop()
            await bot.shutdown()
            
    LOGGER.info("Modules loaded successfully.")
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info("The robot stopped.")
    finally:
        loop.close()

if __name__ == "__main__":
    run()