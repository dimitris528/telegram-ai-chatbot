import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# === Φόρτωση .env ===
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# === Μνήμη συνομιλιών ===
MEMORY_FILE = "memory.json"

# Αν δεν υπάρχει αρχείο, δημιουργείται
if not os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "w") as f:
        json.dump({}, f)

def load_memory():
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

# === Διαχείριση μηνυμάτων ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.chat_id)
    user_message = update.message.text
    memory = load_memory()

    # Αν δεν υπάρχει συνομιλία, φτιάχνουμε νέα
    if user_id not in memory:
        memory[user_id] = []

    # Προσθέτουμε το μήνυμα του χρήστη στη μνήμη
    memory[user_id].append({"role": "user", "content": user_message})

    # Περιορίζουμε το ιστορικό στα τελευταία 10 μηνύματα (για αποδοτικότητα)
    conversation = memory[user_id][-10:]

    # Δημιουργία απάντησης από OpenAI
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=conversation
    )

    bot_reply = response.choices[0].message.content

    # Αποθήκευση απάντησης του bot
    memory[user_id].append({"role": "assistant", "content": bot_reply})
    save_memory(memory)

    # Αποστολή απάντησης πίσω στο Telegram
    await update.message.reply_text(bot_reply)

# === Εκκίνηση bot ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
    