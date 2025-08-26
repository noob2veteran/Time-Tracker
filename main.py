import os
import logging
from datetime import datetime
from collections import defaultdict

# pip install python-telegram-bot apscheduler
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Configuration ---
# It's best to get these from environment variables for security
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TEMP_CHANNEL_ID = os.environ.get("TEMP_CHANNEL_ID", "YOUR_TEMP_CHANNEL_ID_HERE")
MAIN_CHANNEL_ID = os.environ.get("MAIN_CHANNEL_ID", "YOUR_MAIN_CHANNEL_ID_HERE")

# Enable logging to see errors
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
    """Formats the list of tasks for a given day into the desired string format."""
    tasks = tasks_storage.get(day_str, [])
    if not tasks:
        return f"Date: {day_str}\n\nNo tasks recorded."

    header = f"🗓️ Date : {day_str}\n |"
    task_lines = []

    for i, task_item in enumerate(tasks):
        time = task_item["time"]
        task_desc = task_item["task"]

        # Use '└' for the last item, '├' for others
        prefix = "└" if i == len(tasks) - 1 else "├"

        # Handle multi-line tasks
        lines = task_desc.split('\n')
        first_line = f"{prefix}{time}─  {lines[0]}"
        additional_lines = [f" |                     {line}" for line in lines[1:]]

        task_lines.append(first_line)
        task_lines.extend(additional_lines)

    return "\n".join([header] + task_lines)

# --- Bot Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text("Hi! I'm your daily task tracker. Use /settask to add a new task.")

async def settask_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new task."""
    await update.message.reply_text(
        "What task are you starting now? Send me the description.\n\n"
        "Send /cancel to stop."
    )
    return ASKING_TASK

async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the task description and ends the conversation."""
    task_description = update.message.text
    now = datetime.now()

    current_time = now.strftime("%I:%M %p") # e.g., 02:30 PM
    current_date = now.strftime("%Y-%m-%d") # e.g., 2025-08-26

    # Add the new task to our storage
    tasks_storage[current_date].append({"time": current_time, "task": task_description})

    # Format and send the updated list to the temporary channel
    formatted_tasks = format_tasks_for_day(current_date)
    await context.bot.send_message(chat_id=TEMP_CHANNEL_ID, text=formatted_tasks)

    await update.message.reply_text("✅ Task added and log updated!")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("Operation cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Scheduled Job ---
async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the final task list to the main channel and clears the day's tasks."""
    today_str = datetime.now().strftime("%Y-%m-%d")

    if today_str in tasks_storage:
        logger.info(f"Sending daily summary for {today_str}")
        final_summary = format_tasks_for_day(today_str)
        await context.bot.send_message(chat_id=MAIN_CHANNEL_ID, text=final_summary)

        # Clear today's tasks after sending
        del tasks_storage[today_str]
    else:
        logger.info(f"No tasks to summarize for {today_str}")

# --- Main Application Setup ---
async def post_init(application: Application) -> None:
    """Schedules the daily summary job after the application's event loop is running."""
    # Set your timezone correctly!
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(send_daily_summary, 'cron', hour=23, minute=55, args=[application])
    scheduler.start()
    logger.info("Scheduler started successfully.")

def main() -> None:
    """Start the bot."""
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)  # <-- This is the key change
        .build()
    )

    # --- Conversation Handler for adding tasks ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("settask", settask_start)],
        states={
            ASKING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
