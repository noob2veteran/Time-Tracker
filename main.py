import os
import logging
import traceback
import html
import json
from datetime import datetime
from collections import defaultdict
import pytz

from flask import Flask, request
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler

# =====================
# ENV VARIABLES
# =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TEMP_CHANNEL_ID = os.environ.get("TEMP_CHANNEL_ID")
MAIN_CHANNEL_ID = os.environ.get("MAIN_CHANNEL_ID")

if not BOT_TOKEN or not TEMP_CHANNEL_ID or not MAIN_CHANNEL_ID:
    raise ValueError("Please set BOT_TOKEN, TEMP_CHANNEL_ID and MAIN_CHANNEL_ID as environment variables.")

# =====================
# Logging
# =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =====================
# In-memory storage
# =====================
tasks_storage = defaultdict(list)

# =====================
# Conversation States
# =====================
ASKING_TASK = 0

# =====================
# Flask app
# =====================
app = Flask(__name__)

# =====================
# Helper functions
# =====================
def get_indian_time():
    tz = pytz.timezone("Asia/Kolkata")
    return datetime.now(tz)

def format_tasks_for_day(day_str: str) -> str:
    tasks = tasks_storage.get(day_str, [])
    if not tasks:
        return f"Date: {day_str}\n\nNo tasks recorded."
    header = f"🗓️ Date : {day_str}\n |"
    task_lines = []
    for i, task_item in enumerate(tasks):
        time = task_item["time"]
        task_desc = task_item["task"]
        prefix = "└" if i == len(tasks) - 1 else "├"
        lines = task_desc.split('\n')
        first_line = f"{prefix}{time}─  {lines[0]}"
        additional_lines = [f" |                     {line}" for line in lines[1:]]
        task_lines.append(first_line)
        task_lines.extend(additional_lines)
    return "\n".join([header] + task_lines)

# =====================
# Bot Handlers
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm your daily task tracker. Use /settask to add a new task.")

async def settask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "What task are you starting now? Send me the description.\nSend /cancel to stop."
    )
    return ASKING_TASK

async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    task_description = update.message.text
    now = get_indian_time()
    current_time = now.strftime("%I:%M %p")
    current_date = now.strftime("%Y-%m-%d")

    tasks_storage[current_date].append({"time": current_time, "task": task_description})
    
    formatted_tasks = format_tasks_for_day(current_date)
    
    try:
        # Try sending to TEMP_CHANNEL once
        await context.bot.send_message(chat_id=TEMP_CHANNEL_ID, text=formatted_tasks)
    except Exception as e:
        logger.error(f"Failed to send message to TEMP_CHANNEL {TEMP_CHANNEL_ID}: {e}")
        await update.message.reply_text(
            f"❌ Could not send log to the temporary channel. Details: {e}\n"
            "Check if the bot is admin and the channel ID is correct."
        )
        return ConversationHandler.END

    await update.message.reply_text("✅ Task added and log updated!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# =====================
# Scheduled daily summary
# =====================
def send_daily_summary(app: Application):
    today_str = get_indian_time().strftime("%Y-%m-%d")
    if today_str in tasks_storage:
        final_summary = format_tasks_for_day(today_str)
        try:
            app.bot.send_message(chat_id=MAIN_CHANNEL_ID, text=final_summary)
            del tasks_storage[today_str]
            logger.info(f"Daily summary sent for {today_str}")
        except Exception as e:
            logger.error(f"Failed to send daily summary to MAIN_CHANNEL {MAIN_CHANNEL_ID}: {e}")

# =====================
# /myid command for debugging
# =====================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"TEMP_CHANNEL_ID = {TEMP_CHANNEL_ID}\n"
        f"MAIN_CHANNEL_ID = {MAIN_CHANNEL_ID}\n"
        f"Your User ID = {update.effective_user.id}"
    )
    await update.message.reply_text(msg)

# =====================
# Error Handler
# =====================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    logger.error(message)

# =====================
# Initialize bot
# =====================
application = Application.builder().token(BOT_TOKEN).build()
application.add_error_handler(error_handler)

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("settask", settask_start)],
    states={ASKING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)]},
    fallbacks=[CommandHandler("cancel", cancel)],
)
application.add_handler(CommandHandler("start", start))
application.add_handler(conv_handler)
application.add_handler(CommandHandler("myid", myid))

# =====================
# Scheduler
# =====================
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
scheduler.add_job(lambda: send_daily_summary(application), 'cron', hour=23, minute=55)
scheduler.start()
logger.info("Scheduler started successfully.")

# =====================
# Flask webhook
# =====================
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    application.update_queue.put_nowait(update)
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
