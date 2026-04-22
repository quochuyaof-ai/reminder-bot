import os
import json
import logging
from datetime import datetime
from pathlib import Path
import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "bot.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

TOKEN    = "8740699013:AAHQtk6lmx0_DZAYRx4NG4TRowQwt7YNHdg"
TIMEZONE = pytz.timezone("Asia/Ho_Chi_Minh")
DATA_FILE   = Path(__file__).parent / "reminders.json"
CHATID_FILE = Path(__file__).parent / "chat_id.txt"

# Day mapping: Vietnamese -> APScheduler
DAY_MAP = {
    "t2": "mon", "t3": "tue", "t4": "wed",
    "t5": "thu", "t6": "fri", "t7": "sat", "cn": "sun",
    "mon": "mon", "tue": "tue", "wed": "wed",
    "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
}
ALL_DAYS = "mon,tue,wed,thu,fri,sat,sun"

scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# ── Chat ID (auto-detect) ─────────────────────────────────────────────────────

def get_chat_id() -> str:
    if CHATID_FILE.exists():
        return CHATID_FILE.read_text().strip()
    return ""

def set_chat_id(cid: str):
    CHATID_FILE.write_text(cid)

# ── Storage ───────────────────────────────────────────────────────────────────

def load_reminders() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return []

def save_reminders(data: list):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

# ── Scheduler ─────────────────────────────────────────────────────────────────

async def fire_reminder(application: Application, text: str):
    cid = get_chat_id()
    if not cid:
        logger.warning("No chat_id yet, skip reminder")
        return
    await application.bot.send_message(chat_id=cid, text=text)
    logger.info(f"Sent: {text[:60]}")

def rebuild_scheduler(application: Application):
    scheduler.remove_all_jobs()
    for r in load_reminders():
        if r.get("paused"):
            continue
        days = r.get("days", ALL_DAYS)
        scheduler.add_job(
            fire_reminder,
            trigger="cron",
            day_of_week=days,
            hour=r["hour"],
            minute=r["minute"],
            args=[application, r["text"]],
            id=r["id"],
            replace_existing=True,
        )
    logger.info(f"Scheduler: {len(scheduler.get_jobs())} job(s) active")

# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    set_chat_id(cid)
    logger.info(f"Chat ID set: {cid}")
    await update.message.reply_text(
        "🔔 *Reminder Bot đang chạy!*\n\n"
        "📌 Lệnh:\n"
        "`/add 07:30 Uống nước` — nhắc hàng ngày\n"
        "`/add 14:00 Piano t2,t4,t6` — nhắc theo ngày\n"
        "  _(t2=Thứ 2, t3=Thứ 3 ... t7=Thứ 7, cn=CN)_\n"
        "`/delete 1` — xóa theo số thứ tự\n"
        "`/list` — xem toàn bộ lịch\n"
        "`/pause` — tắt tất cả tạm thời\n"
        "`/resume` — bật lại tất cả\n"
        "`/now` — xem giờ VN hiện tại",
        parse_mode="Markdown"
    )

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add HH:MM nội dung
    /add HH:MM nội dung t2,t4,t6
    """
    cid = str(update.effective_chat.id)
    set_chat_id(cid)

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Cú pháp:\n"
            "`/add 07:30 Uống nước` — hàng ngày\n"
            "`/add 14:00 Piano t2,t4,t6` — theo ngày",
            parse_mode="Markdown"
        )
        return

    try:
        h, m = map(int, context.args[0].split(":"))
        assert 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        await update.message.reply_text("❌ Giờ không đúng. Dùng HH:MM, ví dụ 07:30")
        return

    # Check if last arg is a day list
    args_rest = context.args[1:]
    last = args_rest[-1].lower()
    day_tokens = [t.strip() for t in last.replace(" ", "").split(",")]
    if all(t in DAY_MAP for t in day_tokens):
        days = ",".join(DAY_MAP[t] for t in day_tokens)
        text = " ".join(args_rest[:-1])
        days_label = last
    else:
        days = ALL_DAYS
        text = " ".join(args_rest)
        days_label = "hàng ngày"

    if not text:
        await update.message.reply_text("❌ Thiếu nội dung nhắc nhở.")
        return

    reminders = load_reminders()
    new_id = f"r_{h:02d}{m:02d}_{len(reminders)}"
    reminders.append({
        "id": new_id, "hour": h, "minute": m,
        "text": text, "days": days, "paused": False
    })
    reminders.sort(key=lambda x: (x["hour"], x["minute"]))
    save_reminders(reminders)
    rebuild_scheduler(context.application)

    await update.message.reply_text(
        f"✅ Đã thêm: *{h:02d}:{m:02d}* ({days_label}) — {text}",
        parse_mode="Markdown"
    )

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    set_chat_id(cid)
    reminders = load_reminders()
    if not reminders:
        await update.message.reply_text("Chưa có reminder nào.")
        return
    if not context.args:
        lines = [_fmt(i, r) for i, r in enumerate(reminders)]
        await update.message.reply_text("Dùng /delete [số]\n\n" + "\n".join(lines))
        return
    try:
        idx = int(context.args[0]) - 1
        assert 0 <= idx < len(reminders)
    except Exception:
        await update.message.reply_text("❌ Số không hợp lệ. Gõ /list để xem.")
        return
    removed = reminders.pop(idx)
    save_reminders(reminders)
    rebuild_scheduler(context.application)
    await update.message.reply_text(
        f"🗑 Đã xóa: *{removed['hour']:02d}:{removed['minute']:02d}* — {removed['text']}",
        parse_mode="Markdown"
    )

def _fmt(i: int, r: dict) -> str:
    icon = "⏸" if r.get("paused") else "🔔"
    days = r.get("days", ALL_DAYS)
    day_label = "" if days == ALL_DAYS else f" [{days}]"
    return f"{icon} {i+1}. {r['hour']:02d}:{r['minute']:02d}{day_label} — {r['text']}"

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = str(update.effective_chat.id)
    set_chat_id(cid)
    reminders = load_reminders()
    if not reminders:
        await update.message.reply_text("Chưa có reminder nào.\nDùng /add để thêm.")
        return
    lines = ["📋 *Lịch nhắc hàng ngày:*\n"]
    lines += [_fmt(i, r) for i, r in enumerate(reminders)]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_chat_id(str(update.effective_chat.id))
    reminders = load_reminders()
    for r in reminders:
        r["paused"] = True
    save_reminders(reminders)
    scheduler.remove_all_jobs()
    await update.message.reply_text("⏸ Đã tạm dừng tất cả. Dùng /resume để bật lại.")

async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_chat_id(str(update.effective_chat.id))
    reminders = load_reminders()
    for r in reminders:
        r["paused"] = False
    save_reminders(reminders)
    rebuild_scheduler(context.application)
    await update.message.reply_text("▶️ Đã bật lại tất cả reminder.")

async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_chat_id(str(update.effective_chat.id))
    now = datetime.now(TIMEZONE).strftime("%H:%M:%S — %d/%m/%Y")
    await update.message.reply_text(f"🕐 Giờ VN: {now}")

async def catch_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat:
        cid = str(update.effective_chat.id)
        set_chat_id(cid)
        logger.info(f"[CHAT_ID] {cid} | {update.effective_chat.first_name}")

# ── Boot ──────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    rebuild_scheduler(application)
    if not scheduler.running:
        scheduler.start()
    logger.info(f"Bot ready. Chat ID: {get_chat_id() or 'not set yet'}")

def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, catch_all), group=1)
    for cmd, fn in [
        ("start",  cmd_start),
        ("add",    cmd_add),
        ("delete", cmd_delete),
        ("list",   cmd_list),
        ("pause",  cmd_pause),
        ("resume", cmd_resume),
        ("now",    cmd_now),
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
