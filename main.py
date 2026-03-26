"""
BOT 1 - Anonymous Chat
Dua pengguna dipasangkan secara acak dan bisa chat tanpa tahu identitas masing-masing.
"""

import logging
import sqlite3
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ============================================================
# KONFIGURASI — Ganti dengan token bot kamu
# ============================================================
BOT_TOKEN = "8781102117:AAF7ktX8iH4yqRxfQUW9KnYb-8jKTYkLJ3w"
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Database ───────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            username  TEXT,
            status    TEXT DEFAULT 'idle',   -- idle | waiting | chatting
            partner   INTEGER DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id  INTEGER,
            receiver_id INTEGER,
            content    TEXT,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def upsert_user(user_id, username, status='idle', partner=None):
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, username, status, partner)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            status=excluded.status,
            partner=excluded.partner
    """, (user_id, username, status, partner))
    conn.commit()
    conn.close()

def set_status(user_id, status, partner=None):
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status=?, partner=? WHERE user_id=?",
              (status, partner, user_id))
    conn.commit()
    conn.close()

def get_waiting_user(exclude_id):
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE status='waiting' AND user_id != ?",
              (exclude_id,))
    rows = c.fetchall()
    conn.close()
    if rows:
        return random.choice(rows)[0]
    return None

def save_message(sender_id, receiver_id, content):
    conn = sqlite3.connect("anonymous_chat.db")
    c = conn.cursor()
    c.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
              (sender_id, receiver_id, content))
    conn.commit()
    conn.close()

# ─── Handlers ────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username or user.first_name)

    keyboard = [
        [InlineKeyboardButton("🔍 Cari Partner Chat", callback_data="find_partner")],
    ]
    await update.message.reply_text(
        "👋 Selamat datang di *Anonymous Chat*!\n\n"
        "Kamu akan dipasangkan dengan orang asing secara acak.\n"
        "Identitas kamu *tidak akan diketahui* oleh partner.\n\n"
        "Tekan tombol di bawah untuk mulai:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def find_partner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    db_user = get_user(user_id)
    if db_user and db_user[2] == 'chatting':
        await query.message.reply_text("⚠️ Kamu sudah sedang dalam sesi chat. Ketik /stop untuk mengakhiri.")
        return

    # Cari partner yang sedang menunggu
    partner_id = get_waiting_user(user_id)

    if partner_id:
        # Pasangkan keduanya
        set_status(user_id, 'chatting', partner_id)
        set_status(partner_id, 'chatting', user_id)

        await ctx.bot.send_message(
            partner_id,
            "✅ *Partner ditemukan!*\n\nSeseorang ingin chat denganmu. Mulai kirim pesan!\nKetik /stop untuk mengakhiri.",
            parse_mode="Markdown"
        )
        await query.message.reply_text(
            "✅ *Partner ditemukan!*\n\nKamu terhubung dengan orang asing. Mulai kirim pesan!\nKetik /stop untuk mengakhiri.",
            parse_mode="Markdown"
        )
    else:
        # Masuk antrian tunggu
        set_status(user_id, 'waiting')
        await query.message.reply_text(
            "⏳ *Mencari partner...*\n\nKamu sedang dalam antrian. Tunggu sebentar ya!\nKetik /cancel untuk membatalkan.",
            parse_mode="Markdown"
        )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)

    if not db_user or db_user[2] != 'chatting':
        await update.message.reply_text(
            "❌ Kamu belum dalam sesi chat. Ketik /start untuk mulai."
        )
        return

    partner_id = db_user[3]
    text = update.message.text

    # Simpan pesan ke database
    save_message(user_id, partner_id, text)

    # Kirim ke partner
    try:
        await ctx.bot.send_message(partner_id, f"👤 *Stranger:*\n{text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Gagal kirim pesan ke partner: {e}")
        await update.message.reply_text("⚠️ Gagal mengirim pesan. Partner mungkin sudah tidak aktif.")

async def stop_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_user = get_user(user_id)

    if not db_user or db_user[2] not in ('chatting', 'waiting'):
        await update.message.reply_text("❌ Kamu tidak sedang dalam sesi chat.")
        return

    if db_user[2] == 'chatting':
        partner_id = db_user[3]
        set_status(user_id, 'idle')
        set_status(partner_id, 'idle')

        await ctx.bot.send_message(
            partner_id,
            "🔴 *Partner telah mengakhiri sesi chat.*\n\nKetik /start untuk mencari partner baru.",
            parse_mode="Markdown"
        )
        await update.message.reply_text(
            "🔴 *Sesi chat diakhiri.*\n\nKetik /start untuk mencari partner baru.",
            parse_mode="Markdown"
        )
    else:
        set_status(user_id, 'idle')
        await update.message.reply_text("✅ Pencarian dibatalkan.")

async def cancel_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await stop_chat(update, ctx)

# ─── Main ─────────────────────────────────────────────────────

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("cancel", cancel_search))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="find_partner"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot 1 (Anonymous Chat) berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
