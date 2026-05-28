import os
import json
import logging
import requests
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_ID = 112201829
BITRIX_WEBHOOK = "https://logika25.bitrix24.ru/rest/5/fzrqlqrqdjtogj5i"
BUSINESS_PROCESS_ID = 446
DATA_FILE = "/data/deals.json"

# Битрикс ID исполнителей
EXECUTOR_IDS = {
    "Сергей": 1978,
    "Лера": 1770,
    "Алексей Москалев": 1836,
}

EXECUTORS = ["Сергей", "Лера", "Алексей Москалев"]

# ─── STATES ───────────────────────────────────────────────────────────────────
(
    MAIN_MENU,
    ADD_DEAL_ID, ADD_DEAL_NAME,
    DELETE_DEAL_SELECT,
    TIME_SELECT_DEAL, TIME_EXECUTOR_MINUTES, TIME_WHAT_DID, TIME_SELECT_EXECUTOR, TIME_MY_MINUTES,
) = range(9)

# ─── DATA HELPERS ─────────────────────────────────────────────────────────────
def load_deals():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_deals(deals):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)

# ─── BITRIX ───────────────────────────────────────────────────────────────────
def get_deal_stage(deal_id):
    url = f"{BITRIX_WEBHOOK}/crm.deal.get.json"
    try:
        resp = requests.post(url, json={"id": deal_id}, timeout=10)
        data = resp.json()
        return data.get("result", {}).get("STAGE_ID", "")
    except Exception as e:
        logger.error(f"Bitrix get deal error: {e}")
        return ""

def run_bitrix_process(deal_id, executor_minutes, what_did, executor_bitrix_id, my_minutes):
    url = f"{BITRIX_WEBHOOK}/bizproc.workflow.start.json"
    payload = {
        "TEMPLATE_ID": BUSINESS_PROCESS_ID,
        "DOCUMENT_ID": ["crm", "CCrmDocumentDeal", f"DEAL_{deal_id}"],
        "PARAMETERS": {
            "Parameter1": executor_minutes,   # Сколько минут потратил исполнитель
            "Parameter2": what_did,           # Что делал
            "Parameter5": 372,                # Фиксированное число
            "Parameter3": executor_bitrix_id, # ID исполнителя: 1978 (Сергей) или 1770 (Лера)
            "Parameter4": my_minutes,         # Сколько потратил я
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        logger.info(f"Bitrix response: {data}")
        return data.get("result") is not None or "error" not in data
    except Exception as e:
        logger.error(f"Bitrix error: {e}")
        return False

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Добавить сделку")],
            [KeyboardButton("🕐 Добавить время")],
            [KeyboardButton("🗑 Удалить сделку")],
        ],
        resize_keyboard=True
    )

def deals_inline_keyboard(deals, callback_prefix):
    buttons = []
    for deal_id, deal_name in deals.items():
        buttons.append([InlineKeyboardButton(f"#{deal_id} — {deal_name}", callback_data=f"{callback_prefix}:{deal_id}")])
    return InlineKeyboardMarkup(buttons)

def executors_inline_keyboard():
    buttons = [[InlineKeyboardButton(name, callback_data=f"executor:{name}")] for name in EXECUTORS]
    return InlineKeyboardMarkup(buttons)

# ─── GUARD ────────────────────────────────────────────────────────────────────
async def guard(update: Update) -> bool:
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.effective_message.reply_text("⛔ Доступ запрещён.")
        return False
    return True

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    await update.message.reply_text(
        "👋 Привет! Выбери действие:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

# ─── MAIN MENU ROUTER ─────────────────────────────────────────────────────────
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    text = update.message.text

    if text == "➕ Добавить сделку":
        await update.message.reply_text("Введи ID сделки из Битрикс24 (только цифры):")
        return ADD_DEAL_ID

    elif text == "🕐 Добавить время":
        deals = load_deals()
        if not deals:
            await update.message.reply_text("❗ Сначала добавь хотя бы одну сделку.", reply_markup=main_menu_keyboard())
            return MAIN_MENU
        await update.message.reply_text("Выбери сделку:", reply_markup=deals_inline_keyboard(deals, "time_deal"))
        return TIME_SELECT_DEAL

    elif text == "🗑 Удалить сделку":
        deals = load_deals()
        if not deals:
            await update.message.reply_text("❗ Список сделок пуст.", reply_markup=main_menu_keyboard())
            return MAIN_MENU
        await update.message.reply_text("Выбери сделку для удаления:", reply_markup=deals_inline_keyboard(deals, "delete_deal"))
        return DELETE_DEAL_SELECT

    return MAIN_MENU

# ─── ADD DEAL ─────────────────────────────────────────────────────────────────
async def add_deal_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text("❗ ID должен быть числом. Попробуй ещё раз:")
        return ADD_DEAL_ID
    context.user_data["new_deal_id"] = raw
    await update.message.reply_text(f"Отлично! Теперь введи название сделки #{raw}:")
    return ADD_DEAL_NAME

async def add_deal_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    name = update.message.text.strip()
    deal_id = context.user_data["new_deal_id"]
    deals = load_deals()
    deals[deal_id] = name
    save_deals(deals)
    await update.message.reply_text(
        f"✅ Сделка #{deal_id} «{name}» добавлена!",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

# ─── DELETE DEAL ──────────────────────────────────────────────────────────────
async def delete_deal_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split(":")[1]
    deals = load_deals()
    name = deals.pop(deal_id, None)
    save_deals(deals)
    if name:
        await query.edit_message_text(f"🗑 Сделка #{deal_id} «{name}» удалена.")
    else:
        await query.edit_message_text("❗ Сделка не найдена.")
    await context.bot.send_message(query.from_user.id, "Выбери действие:", reply_markup=main_menu_keyboard())
    return MAIN_MENU

# ─── ADD TIME ─────────────────────────────────────────────────────────────────
async def time_select_deal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    deal_id = query.data.split(":")[1]
    deals = load_deals()

    stage = get_deal_stage(deal_id)
    if stage in ("PROPOSAL", "WON", "LOSE"):
        await query.edit_message_text("❌ Эта сделка завершена! Добавь актуальную сделку и удали эту.")
        await context.bot.send_message(query.from_user.id, "Выбери действие:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    context.user_data["time_deal_id"] = deal_id
    context.user_data["time_deal_name"] = deals.get(deal_id, "")
    await query.edit_message_text(f"Сделка: #{deal_id} «{deals.get(deal_id)}»\n\nСколько минут потратил исполнитель?")
    return TIME_EXECUTOR_MINUTES

async def time_executor_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text("❗ Введи число минут:")
        return TIME_EXECUTOR_MINUTES
    context.user_data["executor_minutes"] = int(raw)
    await update.message.reply_text("Что делал исполнитель? (опиши кратко):")
    return TIME_WHAT_DID

async def time_what_did(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    context.user_data["what_did"] = update.message.text.strip()
    await update.message.reply_text("Выбери исполнителя:", reply_markup=executors_inline_keyboard())
    return TIME_SELECT_EXECUTOR

async def time_select_executor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    executor = query.data.split(":")[1]
    context.user_data["executor_name"] = executor
    context.user_data["executor_bitrix_id"] = EXECUTOR_IDS[executor]
    await query.edit_message_text(f"Исполнитель: {executor}\n\nСколько минут потратил я?")
    return TIME_MY_MINUTES

async def time_my_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return ConversationHandler.END
    raw = update.message.text.strip()
    if not raw.isdigit():
        await update.message.reply_text("❗ Введи число минут:")
        return TIME_MY_MINUTES

    my_minutes = int(raw)
    ud = context.user_data
    deal_id = ud["time_deal_id"]
    deal_name = ud["time_deal_name"]
    executor_name = ud["executor_name"]
    executor_minutes = ud["executor_minutes"]
    what_did = ud["what_did"]
    executor_bitrix_id = ud["executor_bitrix_id"]

    await update.message.reply_text("⏳ Отправляю в Битрикс...")

    success = run_bitrix_process(deal_id, executor_minutes, what_did, executor_bitrix_id, my_minutes)

    if success:
        msg = (
            f"✅ Бизнес-процесс запущен!\n\n"
            f"📋 Сделка: #{deal_id} «{deal_name}»\n"
            f"👤 Исполнитель: {executor_name} — {executor_minutes} мин\n"
            f"📝 Что делал: {what_did}\n"
            f"🙋 Я — {my_minutes} мин"
        )
    else:
        msg = (
            f"⚠️ Данные приняты, но Битрикс вернул ошибку.\n"
            f"Проверь ID процесса и права вебхука.\n\n"
            f"📋 Сделка: #{deal_id} «{deal_name}»\n"
            f"👤 Исполнитель: {executor_name} — {executor_minutes} мин\n"
            f"📝 Что делал: {what_did}\n"
            f"🙋 Я — {my_minutes} мин"
        )

    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    return MAIN_MENU

# ─── CANCEL ───────────────────────────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено.", reply_markup=main_menu_keyboard())
    return MAIN_MENU

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
            ADD_DEAL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_deal_id)],
            ADD_DEAL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_deal_name)],
            DELETE_DEAL_SELECT: [CallbackQueryHandler(delete_deal_select, pattern=r"^delete_deal:")],
            TIME_SELECT_DEAL: [CallbackQueryHandler(time_select_deal, pattern=r"^time_deal:")],
            TIME_EXECUTOR_MINUTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_executor_minutes)],
            TIME_WHAT_DID: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_what_did)],
            TIME_SELECT_EXECUTOR: [CallbackQueryHandler(time_select_executor, pattern=r"^executor:")],
            TIME_MY_MINUTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_my_minutes)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
