import os
import logging
import traceback
import html
import json
from datetime import datetime
from collections import defaultdict

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TEMP_CHANNEL_ID = os.environ.get("TEMP_CHANNEL_ID", "YOUR_TEMP_CHANNEL_ID_HERE")
MAIN_CHANNEL_ID = os.environ.get("MAIN_CHANNEL_ID", "YOUR_MAIN_CHANNEL_ID_HERE")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- In-Memory Data Storage ---
tasks_storage = defaultdict(list)

# --- Conversation States ---
ASKING_TASK = 0

# --- Helper Function to Format Tasks ---
def format_tasks_for_day(day_str: str) -> str:
    # ... (This function is the same as before, no changes needed)
    tasks = tasks_storage.get(day_str, [])
    if not tasks:
        return f"Date: {day_str}\n\nNo tasks recorded."
    header = f"🗓️ Date : {day_str}\n |"
    task_lines = []
    for i, task_item in enumerate(tasks):
        time, task_desc = task_item["time"], task_item["task"]
        prefix = "└" if i == len(tasks) - 1 else "├"
        lines = task_desc.split('\n')
        first_line = f"{prefix}{time}─  {lines[0]}"
        additional_lines = [f" |                     {line}" for line in lines[1:]]
        task_lines.append(first_line)
        task_lines.extend(additional_lines)
    return "\n".join([header] + task_lines)

# --- Bot Command Handlers ---
# ... (start, settask_start, receive_task, and cancel are the same as before)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hi! I'm your daily task tracker. Use /settask to add a new task.")
async def settask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What task are you starting now? Send me the description.\n\nSend /cancel to stop.")
    return ASKING_TASK
async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    task_description = update.message.text
    now = datetime.now()
    current_time = now.strftime("%I:%M %p")
    current_date = now.strftime("%Y-%m-%d")
    tasks_storage[current_date].append({"time": current_time, "task": task_description})
    formatted_tasks = format_tasks_for_day(current_date)
    await context.bot.send_message(chat_id=TEMP_CHANNEL_ID, text=formatted_tasks)
    await update.message.reply_text("✅ Task added and log updated!")
    return ConversationHandler.END
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Scheduled Job ---
# ... (send_daily_summary is the same as before)
async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str in tasks_storage:
        logger.info(f"Sending daily summary for {today_str}")
        final_summary = format_tasks_for_day(today_str)
        await context.bot.send_message(chat_id=MAIN_CHANNEL_ID, text=final_summary)
        del tasks_storage[today_str]
    else:
        logger.info(f"No tasks to summarize for {today_str}")

# --- NEW: Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Extract traceback
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Log the full error context
    update_str = update.to_dict() if isinstance(update, Update) else str(update)
    message = (
        f"An exception was raised while handling an update\n"
        f"<pre>update = {html.escape(json.dumps(update_str, indent=2, ensure_ascii=False))}"
        "</pre>\n\n"
        f"<pre>context.chat_data = {html.escape(str(context.chat_data))}</pre>\n\n"
        f"<pre>context.user_data = {html.escape(str(context.user_data))}</pre>\n\n"
        f"<pre>{html.escape(tb_string)}</pre>"
    )
    logger.error(message) # Also log the detailed message for debugging

# --- Main Application Setup ---
async def post_init(application: Application) -> None:
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(send_daily_summary, 'cron', hour=23, minute=55, args=[application])
    scheduler.start()
    logger.info("Scheduler started successfully.")

def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # --- Register Handlers ---
    application.add_error_handler(error_handler) # <-- Add the error handler

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("settask", settask_start)],
        states={ASKING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
