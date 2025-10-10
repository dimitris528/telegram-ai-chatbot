import os
from openai import OpenAI
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not OPENAI_API_KEY or not TELEGRAM_TOKEN:
    logger.error("OPENAI_API_KEY ή TELEGRAM_TOKEN λείπει!")
    raise ValueError("OPENAI_API_KEY ή TELEGRAM_TOKEN λείπει από το .env!")

try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client ξεκίνησε επιτυχώς")
except Exception as e:
    logger.error(f"Σφάλμα κατά την αρχικοποίηση OpenAI: {e}")
    raise

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    logger.info(f"Λήψη μηνύματος από χρήστη: {user_message}")
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": user_message}],
        )
        bot_reply = response.choices[0].message.content
        logger.info(f"Απάντηση από OpenAI: {bot_reply}")
        await update.message.reply_text(bot_reply)
    except Exception as e:
        logger.error(f"Σφάλμα κατά την κλήση OpenAI: {e}")
        await update.message.reply_text("Συγγνώμη, υπήρξε πρόβλημα.")

def main():
    logger.info("Ο Telegram bot ξεκινά...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Handler προστέθηκε, ξεκινά το polling...")
    app.run_polling()

if __name__ == "__main__":
    main()