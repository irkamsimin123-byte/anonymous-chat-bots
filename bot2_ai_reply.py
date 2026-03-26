"""
BOT 2 - AI Auto Reply
Jika partner tidak membalas dalam X detik, AI (Gemini gratis) otomatis membalas
agar percakapan tetap berjalan.
"""

import logging
import sqlite3
import asyncio
import time
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ============================================================
# KONFIGURASI — Ganti semua nilai di sini
# ============================================================
BOT_TOKEN        = "8522846951:AAGkkYTO1O9qpz_oiLb5FdMj57W2IoK6yiw"
GEMINI_API_KEY   = "AIzaSyAGitoGbIpeGGx4JjWvZRsoLNUanPO-c-A"
DB_PATH          = "anonymous_chat.db"   # harus sama dengan Bot 1
DELAY_DETIK      = 30   # AI balas jika partner diam selama X detik
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")   # gratis & cepat

# Simpan waktu pesan terakhir: {user_id: timestamp}
last_message_time: dict[int, float] = {}
# Simpan riwayat percakapan untuk konteks AI: {user_id: [pesan]}
chat_history: dict[int, list] = {}

# ─── Database (baca dari DB Bot 1) ───────────────────────────

def get_chatting_pairs():
    """Ambil semua pasangan yang sedang chatting."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, partner FROM users WHERE status='chatting'")
    rows = c.fetchall()
    conn.close()
    return rows

def get_recent_messages(user_id, partner_id, limit=10):
    """Ambil riwayat pesan antara dua user untuk konteks AI."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT sender_id, content FROM messages
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, partner_id, partner_id, user_id, limit))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def save_message(sender_id, receiver_id, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
              (sender_id, receiver_id, content))
    conn.commit()
    conn.close()

# ─── AI Reply ────────────────────────────────────────────────

async def generate_ai_reply(user_id, partner_id) -> str:
    """Generate balasan AI berdasarkan riwayat percakapan."""
    messages = get_recent_messages(user_id, partner_id)

    history_text = ""
    for sender_id, content in messages:
        label = "Stranger" if sender_id == user_id else "Kamu"
        history_text += f"{label}: {content}\n"

    prompt = f"""Kamu adalah AI yang membantu menjaga percakapan anonim tetap berjalan.
Berperan sebagai "Stranger" (orang asing) yang sedang chat anonim.
Balas dengan natural, santai, seperti orang biasa chatting.
Gunakan bahasa Indonesia yang casual. Maksimal 2-3 kalimat.
Jangan menyebut bahwa kamu adalah AI.

Riwayat percakapan terakhir:
{history_text if history_text else "(Belum ada pesan)"}

Berikan balasan yang natural untuk melanjutkan percakapan:"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "Hei, masih di sini kok 😊 Lagi ngapain?"

# ─── Auto Reply Monitor ───────────────────────────────────────

async def monitor_and_autoreply(app):
    """Loop yang cek setiap 10 detik apakah ada partner yang diam terlalu lama."""
    logger.info("Monitor auto-reply aktif...")
    while True:
        await asyncio.sleep(10)
        try:
            pairs = get_chatting_pairs()
            now = time.time()

            processed = set()
            for user_id, partner_id in pairs:
                if (user_id, partner_id) in processed or (partner_id, user_id) in processed:
                    continue
                processed.add((user_id, partner_id))

                # Cek apakah partner (user_id) sudah diam terlalu lama
                last = last_message_time.get(user_id, 0)
                if last == 0:
                    # Belum ada pesan sama sekali, skip
                    continue

                if now - last >= DELAY_DETIK:
                    # AI balas ke partner (partner_id menerima balasan)
                    ai_reply = await generate_ai_reply(user_id, partner_id)

                    try:
                        await app.bot.send_message(
                            partner_id,
                            f"👤 *Stranger:*\n{ai_reply}",
                            parse_mode="Markdown"
                        )
                        # Simpan ke DB agar konteks AI terus berkembang
                        save_message(user_id, partner_id, ai_reply)
                        # Reset timer agar tidak spam
                        last_message_time[user_id] = now
                        logger.info(f"AI membalas untuk user {user_id} ke {partner_id}")
                    except Exception as e:
                        logger.error(f"Gagal kirim AI reply: {e}")
        except Exception as e:
            logger.error(f"Monitor error: {e}")

# ─── Handlers ────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Catat waktu pesan terakhir dari user."""
    user_id = update.effective_user.id
    last_message_time[user_id] = time.time()

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Bot AI Auto-Reply aktif!*\n\n"
        "Bot ini bekerja di belakang layar.\n"
        "Jika partner diam lebih dari {} detik, AI akan membalas secara otomatis.".format(DELAY_DETIK),
        parse_mode="Markdown"
    )

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pairs = get_chatting_pairs()
    await update.message.reply_text(
        f"📊 *Status Bot AI*\n\n"
        f"Pasangan aktif: {len(pairs) // 2}\n"
        f"Delay auto-reply: {DELAY_DETIK} detik",
        parse_mode="Markdown"
    )

# ─── Main ─────────────────────────────────────────────────────

async def post_init(app):
    """Jalankan monitor setelah bot siap."""
    asyncio.create_task(monitor_and_autoreply(app))

def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot 2 (AI Auto-Reply) berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
