import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, filters
from mcrcon import MCRcon

# ─── Загрузка .env ────────────────────────────────────────────────────────────
load_dotenv()

# ─── Конфигурация ─────────────────────────────────────────────────────────────
TOKEN         = os.getenv("TG_TOKEN")
RCON_HOST     = os.getenv("RCON_HOST", "127.0.0.1")
RCON_PORT     = int(os.getenv("RCON_PORT", "25575"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")
SUPER_ADMINS  = {int(i) for i in os.getenv("SUPER_ADMINS", "").split(",") if i}

ROOT          = Path(__file__).parent
ALLOWED_FILE  = ROOT / "allowed.json"
IMAGES_FILE   = ROOT / "images.json"

# ─── Цветовой фильтр ──────────────────────────────────────────────────────────
REMOVE_ONLY_GOLD = False  # True – удалить только §6, False – удалить все §x
_COLOR_REGEX = re.compile(r"§6" if REMOVE_ONLY_GOLD else r"§.")

def strip_colors(text: str) -> str:
    return _COLOR_REGEX.sub("", text)

# ─── Allowed users ────────────────────────────────────────────────────────────
if ALLOWED_FILE.exists():
    ALLOWED_USERS = set(json.loads(ALLOWED_FILE.read_text()))
else:
    ALLOWED_USERS = set()
    ALLOWED_FILE.write_text("[]")

# ─── Image map ────────────────────────────────────────────────────────────────
try:
    if IMAGES_FILE.exists() and IMAGES_FILE.stat().st_size:
        IMAGE_MAP = json.loads(IMAGES_FILE.read_text())
    else:
        IMAGE_MAP = {}
        if not IMAGES_FILE.exists():
            IMAGES_FILE.write_text("{}")
except json.JSONDecodeError:
    IMAGE_MAP = {}

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("rcon‑bot")

# ─── Вспомогалки ──────────────────────────────────────────────────────────────

def save_allowed():
    ALLOWED_FILE.write_text(json.dumps(sorted(ALLOWED_USERS)))

def is_super(uid: int) -> bool:
    return uid in SUPER_ADMINS

def is_allowed(uid: int) -> bool:
    return uid in ALLOWED_USERS or is_super(uid)

def rcon_execute(cmd: str) -> str:
    with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
        return mcr.command(cmd)

# ─── unified reply helper ─────────────────────────────────────────────────────
async def reply(update: Update, text: str, key: Optional[str] = None, *, parse_mode: Optional[str] = None):
    """Отправляет либо фото с подписью, либо просто текст (1 сообщение)."""
    img = None
    if key:
        img = IMAGE_MAP.get(key) or IMAGE_MAP.get(key.split(":")[0])

    if img:
        try:
            if img.startswith("http://") or img.startswith("https://"):
                await update.message.reply_photo(img, caption=text, parse_mode=parse_mode)
            else:
                path = ROOT / img
                if path.exists():
                    await update.message.reply_photo(path.read_bytes(), caption=text, parse_mode=parse_mode)
                else:
                    logger.warning("Image key '%s' → файл %s не найден", key, path)
                    await update.message.reply_text(text, parse_mode=parse_mode)
        except Exception:
            logger.exception("Не удалось отправить фото %s", img)
            await update.message.reply_text(text, parse_mode=parse_mode)
    else:
        await update.message.reply_text(text, parse_mode=parse_mode)

# ─── Хендлеры ─────────────────────────────────────────────────────────────────
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
                "👋 Привет! Я RCON‑бот.\nСправка – /help\nВыполнить – /cmd <команда>",
                key="start")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update,
                "⚒ *RCON‑бот*\n"
                "/cmd `<команда>` – выполнить\n"
                "/online – список игроков онлайн\n"
                "/tps – TPS сервера\n"
                "Админ: /adduser /deluser /listusers",
                key="help", parse_mode="Markdown")

async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await reply(update, "⛔ У тебя нет доступа.", key="no_access")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Пример: `/cmd say Привет`", parse_mode="Markdown")
        return

    mc_cmd = " ".join(context.args)
    subkey = mc_cmd.split()[0]
    logger.info("RCON %s → %s", uid, mc_cmd)
    try:
        out = rcon_execute(mc_cmd)
        out_clean = strip_colors(out)
        text = f"✅ Вывод:\n`{out_clean}`" if out_clean.strip() else "✅ Команда выполнена, ответ пустой."
        await reply(update, text, key=f"cmd:{subkey}", parse_mode="Markdown")
    except Exception as e:
        await reply(update, f"❌ Ошибка: {e}", key="error")

async def online_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await reply(update, "⛔ У тебя нет доступа.", key="no_access")
        return

    try:
        out = rcon_execute("list")
        out_clean = strip_colors(out)
        await reply(update, f"👥 Онлайн:\n`{out_clean}`", key="online", parse_mode="Markdown")
    except Exception as e:
        await reply(update, f"❌ Ошибка: {e}", key="error")

async def tps_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await reply(update, "⛔ У тебя нет доступа.", key="no_access")
        return

    try:
        out = rcon_execute("tps")
        out_clean = strip_colors(out)
        await reply(update, f"⚡ TPS:\n`{out_clean}`", key="tps", parse_mode="Markdown")
    except Exception as e:
        await reply(update, f"❌ Ошибка: {e}", key="error")

# ─── Админ хендлеры ───────────────────────────────────────────────────────────
async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /adduser <TelegramID>")
        return
    try:
        new_id = int(context.args[0])
        ALLOWED_USERS.add(new_id)
        save_allowed()
        await update.message.reply_text(f"✅ {new_id} добавлен.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")

async def deluser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Использование: /deluser <TelegramID>")
        return
    try:
        rem_id = int(context.args[0])
        ALLOWED_USERS.discard(rem_id)
        save_allowed()
        await update.message.reply_text(f"✅ {rem_id} удалён.")
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")

async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super(update.effective_user.id):
        return
    if ALLOWED_USERS:
        txt = "\n".join(f"• {u}" for u in sorted(ALLOWED_USERS))
        await update.message.reply_text(f"*Разрешённые:*\n{txt}", parse_mode="Markdown")
    else:
        await update.message.reply_text("Список пуст.")

# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    if not TOKEN or not RCON_PASSWORD:
        raise RuntimeError("TG_TOKEN и RCON_PASSWORD должны быть заданы (.env).")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cmd", cmd, filters.ChatType.GROUPS | filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("online", online_cmd, filters.ChatType.GROUPS | filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("tps", tps_cmd, filters.ChatType.GROUPS | filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("adduser", adduser))
    app.add_handler(CommandHandler("deluser", deluser))
    app.add_handler(CommandHandler("listusers", listusers))

    logger.info("Bot started 🟢")
    app.run_polling()

if __name__ == "__main__":
    main()
