"""ZERUX AFK BOT - Minecraft serverlar uchun AFK bot (Telegram orqali)."""
import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import BotCommand
from telegram.ext import (Application, CommandHandler, ConversationHandler,
                          MessageHandler, filters)

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("zerux-afk")

# ===================== VARIABLES (Railway -> Variables) =====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")                      # majburiy
AFK_HOURS = float(os.getenv("AFK_HOURS", "72"))              # 72 soat = 3 kun
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "50"))          # bir vaqtda eng ko'p AFK bot
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "15"))    # qayta ulanish (sek, kengayib boradi)
MAX_FAILS = int(os.getenv("MAX_FAILS", "20"))                # ketma-ket ulana olmasa to'xtatish
TZ = timezone(timedelta(hours=float(os.getenv("TZ_OFFSET", "5"))))  # UTC+5
DB_PATH = os.path.abspath(os.getenv("DB_PATH", "afk.db"))    # Volume bo'lsa: /data/afk.db
# ============================================================================

NODE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mc_client.js")
PRIVATE = filters.ChatType.PRIVATE

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute(
    """CREATE TABLE IF NOT EXISTS afk_sessions(
        user_id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, host TEXT NOT NULL,
        port INTEGER NOT NULL, username TEXT NOT NULL, started REAL NOT NULL, ends REAL NOT NULL)"""
)
db.commit()

RUN = {}  # user_id -> {"task", "proc", "state", "fails", "announced", "last_notice"}
HOST, PORT, NAME = range(3)


# ------------------------------- yordamchilar -------------------------------
def left(sec):
    sec = max(0, int(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return (f"{d} kun " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"


def stamp(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def split_hostport(text):
    m = re.fullmatch(r"([A-Za-z0-9.\-]+)(?::(\d{1,5}))?", text.strip())
    if not m:
        raise ValueError("Manzil noto'g'ri. Masalan: play.example.com")
    port = int(m.group(2)) if m.group(2) else None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Port 1 dan 65535 gacha bo'lishi kerak.")
    return m.group(1), port


def check_host(host):
    """Ichki/lokal manzillarga ulanishni bloklaydi. 'ok' | 'unresolved' | 'private'."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return "unresolved"
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            return "private"
    return "ok"


def get_session(uid):
    return db.execute("SELECT * FROM afk_sessions WHERE user_id = ?", (uid,)).fetchone()


def delete_session(uid):
    db.execute("DELETE FROM afk_sessions WHERE user_id = ?", (uid,))
    db.commit()


def kill(proc):
    if proc is not None and proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def notify(app, chat_id, text):
    try:
        await app.bot.send_message(chat_id, text)
    except Exception as e:
        log.warning("Xabar yuborilmadi: %s", e)


STATE_LABEL = {"online": "🟢 Onlayn", "connecting": "🟡 Ulanmoqda...", "reconnecting": "🟠 Qayta ulanmoqda..."}


def status_text(s):
    st = RUN.get(s["user_id"], {})
    return (
        "📊 Holat ma'lumoti\n\n"
        f"🌍 Server: {s['host']}:{s['port']}\n"
        f"🤖 Username: {s['username']}\n"
        f"📡 Ulanish: {STATE_LABEL.get(st.get('state'), '—')}\n"
        f"⏳ Qolgan vaqt: {left(s['ends'] - time.time())}\n"
        f"🕐 Boshlangan: {stamp(s['started'])}\n\n"
        "🎮 Yaxshi o'yin!"
    )


# ------------------------------ AFK sessiyalari ------------------------------
async def finish(app, uid, chat_id, text):
    RUN.pop(uid, None)
    delete_session(uid)
    await notify(app, chat_id, text)


async def read_events(app, chat_id, st, proc):
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "online":
            st["state"] = "online"
            st["fails"] = 0
            if not st["announced"]:
                st["announced"] = True
                await notify(app, chat_id, "🟢 Bot serverga ulandi va AFK holatda turibdi.\nHolatni ko'rish: /status")
        elif kind == "kicked":
            if time.time() - st["last_notice"] > 600:
                st["last_notice"] = time.time()
                await notify(app, chat_id, f"⚠️ Bot serverdan chiqarildi: {ev.get('reason', '')}\nQayta ulanmoqda...")
        elif kind == "error":
            log.info("MC xato: %s", ev.get("message"))
    await proc.wait()


async def session_loop(app, uid, st):
    proc = None
    chat_id = None
    expired = "⏰ 3 kunlik AFK vaqti tugadi.\nQaytadan boshlash uchun /start yozing."
    try:
        while True:
            s = get_session(uid)
            if s is None:
                RUN.pop(uid, None)
                return
            chat_id = s["chat_id"]
            remaining = s["ends"] - time.time()
            if remaining <= 0:
                await finish(app, uid, chat_id, expired)
                return

            st["state"] = "connecting"
            proc = await asyncio.create_subprocess_exec(
                "node", NODE_SCRIPT, s["host"], str(s["port"]), s["username"],
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            st["proc"] = proc
            try:
                await asyncio.wait_for(read_events(app, chat_id, st, proc), timeout=remaining)
            except asyncio.TimeoutError:
                kill(proc)
                await finish(app, uid, chat_id, expired)
                return
            kill(proc)

            was_online = st["state"] == "online"
            st["state"] = "reconnecting"
            if was_online:
                if time.time() - st["last_notice"] > 600:
                    st["last_notice"] = time.time()
                    await notify(app, chat_id, "⚠️ Bot serverdan uzildi. Qayta ulanmoqda...")
            else:
                st["fails"] += 1
                if st["fails"] >= MAX_FAILS:
                    await finish(app, uid, chat_id,
                                 "❌ Serverga ulana olmadim (server o'chiq yoki ma'lumot noto'g'ri bo'lishi mumkin).\n"
                                 "AFK to'xtatildi. Qaytadan boshlash uchun /start yozing.")
                    return
            await asyncio.sleep(min(RECONNECT_DELAY * (2 ** min(st["fails"], 3)), 120))
    except asyncio.CancelledError:
        kill(proc)
        raise
    except Exception:
        log.exception("Sessiya xatosi")
        kill(proc)
        if chat_id:
            await finish(app, uid, chat_id, "❌ Ichki xato yuz berdi. AFK to'xtatildi. /start bilan qayta boshlang.")


def launch(app, uid):
    st = {"state": "connecting", "proc": None, "fails": 0, "announced": False, "last_notice": 0.0, "task": None}
    RUN[uid] = st
    st["task"] = asyncio.create_task(session_loop(app, uid, st))


async def stop_session(uid):
    st = RUN.pop(uid, None)
    if st:
        st["task"].cancel()
        await asyncio.gather(st["task"], return_exceptions=True)
    delete_session(uid)


# ------------------------------ /start dialogi ------------------------------
async def cmd_start(update, ctx):
    msg, uid = update.effective_message, update.effective_user.id
    s = get_session(uid)
    if s:
        await msg.reply_text(status_text(s) + "\n\nTo'xtatib, qaytadan boshlash uchun avval /stop yozing.")
        return ConversationHandler.END
    if len(RUN) >= MAX_SESSIONS:
        await msg.reply_text("⏳ Bot hozir band (joylar to'lgan). Keyinroq /start yozib ko'ring.")
        return ConversationHandler.END
    ctx.user_data.clear()
    await msg.reply_text(
        "👋 Salom!\n"
        "Bu bot Minecraft serveringizda 3 kun davomida AFK bo'lib turadi.\n\n"
        "1/3 - Server IP (manzil) ni yuboring.\n"
        "Masalan: play.example.com"
    )
    return HOST


async def got_host(update, ctx):
    msg = update.effective_message
    try:
        host, port = split_hostport(msg.text)
    except ValueError as e:
        await msg.reply_text(f"❌ {e}\nQaytadan yuboring yoki /cancel.")
        return HOST
    result = await asyncio.get_running_loop().run_in_executor(None, check_host, host)
    if result == "unresolved":
        await msg.reply_text("❌ Bu manzil topilmadi. IP to'g'ri yozilganini tekshiring va qaytadan yuboring.")
        return HOST
    if result == "private":
        await msg.reply_text("❌ Faqat internetdagi (ochiq) serverlarga ulanish mumkin. Boshqa manzil yuboring.")
        return HOST
    ctx.user_data["host"] = host
    if port:
        ctx.user_data["port"] = port
        await msg.reply_text("3/3 - Bot qaysi username bilan kirsin? (3-16 ta harf, raqam yoki _)")
        return NAME
    await msg.reply_text("2/3 - Port ni yuboring.\nOdatda: 25565")
    return PORT


async def got_port(update, ctx):
    msg = update.effective_message
    t = msg.text.strip()
    if not t.isdigit() or not 1 <= int(t) <= 65535:
        await msg.reply_text("❌ Port 1 dan 65535 gacha raqam bo'lishi kerak. Masalan: 25565")
        return PORT
    ctx.user_data["port"] = int(t)
    await msg.reply_text("3/3 - Bot qaysi username bilan kirsin? (3-16 ta harf, raqam yoki _)")
    return NAME


async def got_name(update, ctx):
    msg, uid = update.effective_message, update.effective_user.id
    name = msg.text.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
        await msg.reply_text("❌ Username 3-16 ta harf, raqam yoki _ dan iborat bo'lishi kerak. Qaytadan yuboring.")
        return NAME
    host, port = ctx.user_data.get("host"), ctx.user_data.get("port")
    if not host or not port:
        await msg.reply_text("Xatolik. Qaytadan boshlang: /start")
        return ConversationHandler.END
    if uid in RUN or get_session(uid):
        await msg.reply_text("ℹ️ Siz allaqachon AFK rejimidasiz. /status")
        return ConversationHandler.END
    if len(RUN) >= MAX_SESSIONS:
        await msg.reply_text("⏳ Bot hozir band (joylar to'lgan). Keyinroq /start yozib ko'ring.")
        return ConversationHandler.END
    busy = db.execute(
        "SELECT 1 FROM afk_sessions WHERE host = ? COLLATE NOCASE AND port = ? AND username = ? COLLATE NOCASE",
        (host, port, name),
    ).fetchone()
    if busy:
        await msg.reply_text("❌ Bu username shu serverda band. Boshqa username yuboring.")
        return NAME

    now = time.time()
    ends = now + AFK_HOURS * 3600
    db.execute("INSERT INTO afk_sessions VALUES (?,?,?,?,?,?,?)", (uid, msg.chat_id, host, port, name, now, ends))
    db.commit()
    launch(ctx.application, uid)
    ctx.user_data.clear()
    await msg.reply_text(
        "✅ AFK rejimi yoqildi!\n\n"
        f"🌍 Server: {host}:{port}\n"
        f"🤖 Username: {name}\n"
        f"🕒 Qolgan vaqt: {left(ends - now)}\n\n"
        "Bot ulanganini tekshirish: /status\n"
        "To'xtatish: /stop\n"
        "Eslatma: o'zingiz shu username bilan o'ynamoqchi bo'lsangiz, avval /stop yozing."
    )
    return ConversationHandler.END


async def cmd_cancel(update, ctx):
    ctx.user_data.clear()
    await update.effective_message.reply_text("Bekor qilindi. Boshlash uchun /start yozing.")
    return ConversationHandler.END


# ------------------------------ boshqa buyruqlar ------------------------------
async def cmd_status(update, ctx):
    s = get_session(update.effective_user.id)
    if not s:
        await update.effective_message.reply_text("ℹ️ Siz AFK rejimida emassiz. Boshlash uchun /start yozing.")
        return
    await update.effective_message.reply_text(status_text(s))


async def cmd_time(update, ctx):
    s = get_session(update.effective_user.id)
    if not s:
        await update.effective_message.reply_text("ℹ️ Siz AFK rejimida emassiz. Boshlash uchun /start yozing.")
        return
    await update.effective_message.reply_text(f"⏳ Qolgan vaqt: {left(s['ends'] - time.time())}")


async def cmd_stop(update, ctx):
    uid = update.effective_user.id
    s = get_session(uid)
    if not s:
        await update.effective_message.reply_text("ℹ️ Siz AFK rejimida emassiz.")
        return
    spent = time.time() - s["started"]
    await stop_session(uid)
    await update.effective_message.reply_text(
        f"🛑 AFK rejimi o'chirildi.\nJami AFK vaqti: {left(spent)}\n\nQaytadan boshlash uchun /start yozing."
    )


# ----------------------------- ishga tushirish -----------------------------
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "AFK botni boshlash"),
        BotCommand("status", "Holatni tekshirish"),
        BotCommand("time", "Qolgan vaqt"),
        BotCommand("stop", "AFK rejimini o'chirish"),
    ])
    now = time.time()
    for s in db.execute("SELECT * FROM afk_sessions").fetchall():
        if s["ends"] <= now:
            delete_session(s["user_id"])
        else:
            launch(app, s["user_id"])
    log.info("Bot ishga tushdi. Tiklangan sessiyalar: %d", len(RUN))


async def post_shutdown(app):
    for st in list(RUN.values()):
        kill(st["proc"])
        st["task"].cancel()


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN topilmadi. Railway -> Variables ga qo'shing.")
    app = Application.builder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    text = filters.TEXT & ~filters.COMMAND & PRIVATE
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start, filters=PRIVATE)],
        states={
            HOST: [MessageHandler(text, got_host)],
            PORT: [MessageHandler(text, got_port)],
            NAME: [MessageHandler(text, got_name)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel, filters=PRIVATE)],
        allow_reentry=True,
    ))
    app.add_handler(CommandHandler("status", cmd_status, filters=PRIVATE))
    app.add_handler(CommandHandler("time", cmd_time, filters=PRIVATE))
    app.add_handler(CommandHandler("stop", cmd_stop, filters=PRIVATE))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
