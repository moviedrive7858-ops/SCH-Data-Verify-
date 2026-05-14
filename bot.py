import os
import logging
import json
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from gsheet_data import GSheetData
from keep_alive import keep_alive

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "8714578868"))
GOOGLE_SPREADSHEET_URL = os.environ.get(
    "GOOGLE_SPREADSHEET_URL",
    "https://docs.google.com/spreadsheets/d/1Q281_R_MrEhEIg1PpeXbYgXTakNjrkTFVDhuZbmdLJk/edit?usp=drive_link"
)

# Initialize GSheetData
gsheet_data = None
try:
    gsheet_data = GSheetData()
    logger.info("Google Sheet data loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load Google Sheet data: {e}")

# State management for each user (keyed by user_id – each user has independent state)
user_states = {}

# Pagination sizes
PAGE_SIZE = 8           # Default for Township, RHC
PAGE_SIZE_SMALL = 5     # For Sub-center and Village lists

# Timeout for message auto-deletion (in seconds)
MESSAGE_TIMEOUT = 120

# Level constants
SHEET_SELECT = "sheet_select"
TOWNSHIP_SELECT = "township_select"
RHC_SELECT = "rhc_select"
SUBCENTER_SELECT = "subcenter_select"
VILLAGE_SELECT = "village_select"
MONTH_SELECT = "month_select"
YEARLY_TOTAL_SELECT = "yearly_total_select"
TOWNSHIP_STOCK_SELECT = "township_stock_select"
TOWNSHIP_TESTING_SELECT = "township_team_testing_select"
DISPLAY_PROFILE = "display_profile_data"
DISPLAY_MONTHLY = "display_monthly_data"
DISPLAY_YEARLY = "display_yearly_total"
DISPLAY_TOWNSHIP_STOCK = "display_township_stock"
DISPLAY_TOWNSHIP_TESTING = "display_township_team_testing"
BACK = "back"
PAGE = "page"
CLOSE = "close"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


# ─── COMMANDS ───────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"👋 မင်္ဂလာပါ {user.first_name}!\n\n"
        "📊 /check_data ကို နှိပ်ပြီး Spreadsheet Data ကြည့်ရှုနိုင်ပါသည်။"
    )


async def check_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Private chat: owner only
    if update.effective_chat.type == "private" and user_id != OWNER_ID:
        await update.message.reply_text("⛔ Private chat တွင် Owner သာ အသုံးပြုနိုင်ပါသည်။")
        return

    if gsheet_data is None:
        await update.message.reply_text("⚠️ Google Sheet data မရနိုင်သေးပါ။ ခဏစောင့်ပေးပါ။")
        return

    # Clean previous session for THIS user only
    await _cleanup_old_message(context, user_id, chat_id)

    # Initialize user state (independent per user)
    user_states[user_id] = {
        "history": [],
        "level": SHEET_SELECT,
        "sheet": None,
        "township": None,
        "rhc": None,
        "subcenter": None,
        "village": None,
        "month": None,
        "page": 0,
        "chat_id": chat_id,
    }

    text, kb = _build_sheet_select()
    message = await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    user_states[user_id]["message_id"] = message.message_id
    _schedule_deletion(context, chat_id, message.message_id, user_id)


# ─── CALLBACK HANDLER ───────────────────────────────────────

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if user_id not in user_states:
        await query.edit_message_text("⏰ Session ကုန်သွားပါပြီ။ /check_data ကို ပြန်နှိပ်ပါ။")
        return

    state = user_states[user_id]
    parts = query.data.split(":", 1)
    action = parts[0]
    value = parts[1] if len(parts) > 1 else None

    # ── Close ──
    if action == CLOSE:
        try:
            await query.message.delete()
        except Exception:
            pass
        _remove_scheduled(context, user_id)
        if user_id in user_states:
            del user_states[user_id]
        return

    # ── Pagination ──
    if action == PAGE:
        page_str, level = value.split(":", 1)
        state["page"] = int(page_str)
        state["level"] = level
        text, kb = _build_level(state)
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        _reschedule(context, chat_id, state, user_id)
        return

    # ── Back ──
    if action == BACK:
        if state["history"]:
            prev = state["history"].pop()
            state["level"] = prev["level"]
            state["sheet"] = prev["sheet"]
            state["township"] = prev["township"]
            state["rhc"] = prev["rhc"]
            state["subcenter"] = prev["subcenter"]
            state["village"] = prev["village"]
            state["month"] = prev["month"]
            state["page"] = prev["page"]
        else:
            state["level"] = SHEET_SELECT
            state["sheet"] = None
            state["page"] = 0
        text, kb = _build_level(state)
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        _reschedule(context, chat_id, state, user_id)
        return

    # ── Save history before moving forward ──
    state["history"].append({
        "level": state["level"],
        "sheet": state["sheet"],
        "township": state["township"],
        "rhc": state["rhc"],
        "subcenter": state["subcenter"],
        "village": state["village"],
        "month": state["month"],
        "page": state["page"],
    })

    # ── Navigate forward ──
    if action == SHEET_SELECT:
        state["sheet"] = value
        state["level"] = TOWNSHIP_SELECT
        state["page"] = 0
    elif action == TOWNSHIP_SELECT:
        state["township"] = value
        state["level"] = RHC_SELECT
        state["page"] = 0
    elif action == RHC_SELECT:
        state["rhc"] = value
        state["level"] = SUBCENTER_SELECT
        state["page"] = 0
    elif action == SUBCENTER_SELECT:
        state["subcenter"] = value
        state["level"] = VILLAGE_SELECT
        state["page"] = 0
    elif action == VILLAGE_SELECT:
        state["village"] = value
        if state["sheet"] in ("Stock", "Testing"):
            state["level"] = MONTH_SELECT
        else:
            state["level"] = DISPLAY_PROFILE
        state["page"] = 0
    elif action == MONTH_SELECT:
        state["month"] = value
        state["level"] = DISPLAY_MONTHLY
    elif action == YEARLY_TOTAL_SELECT:
        state["level"] = DISPLAY_YEARLY
    elif action == TOWNSHIP_STOCK_SELECT:
        state["level"] = DISPLAY_TOWNSHIP_STOCK
    elif action == TOWNSHIP_TESTING_SELECT:
        state["level"] = DISPLAY_TOWNSHIP_TESTING

    text, kb = _build_level(state)
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    _reschedule(context, chat_id, state, user_id)


# ─── BUILD MESSAGES ─────────────────────────────────────────

def _build_level(state):
    level = state["level"]
    if level == SHEET_SELECT:
        return _build_sheet_select()
    elif level == TOWNSHIP_SELECT:
        return _build_township(state)
    elif level == RHC_SELECT:
        return _build_rhc(state)
    elif level == SUBCENTER_SELECT:
        return _build_subcenter(state)
    elif level == VILLAGE_SELECT:
        return _build_village(state)
    elif level == MONTH_SELECT:
        return _build_month(state)
    elif level == DISPLAY_PROFILE:
        return _build_profile_data(state)
    elif level == DISPLAY_MONTHLY:
        return _build_monthly_data(state)
    elif level == DISPLAY_YEARLY:
        return _build_yearly_data(state)
    elif level == DISPLAY_TOWNSHIP_STOCK:
        return _build_township_stock_data(state)
    elif level == DISPLAY_TOWNSHIP_TESTING:
        return _build_township_team_testing_data(state)
    return "❌ Unknown level", InlineKeyboardMarkup([])


def _build_sheet_select():
    text = "📊 <b>Data Sheets</b>\n\nSheet တစ်ခုကို ရွေးချယ်ပါ:"
    keyboard = [
        [InlineKeyboardButton("📋 Profile", callback_data=f"{SHEET_SELECT}:Profile")],
        [InlineKeyboardButton("📦 Stock", callback_data=f"{SHEET_SELECT}:Stock")],
        [InlineKeyboardButton("🧪 Testing", callback_data=f"{SHEET_SELECT}:Testing")],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _build_township(state):
    sheet = state["sheet"]
    townships = gsheet_data.get_townships(sheet)
    text = f"📊 <b>{sheet}</b>\n\n🏙 Township ရွေးချယ်ပါ:"
    kb = _paginated_buttons(townships, TOWNSHIP_SELECT, state["page"], state["level"], PAGE_SIZE)
    return text, kb


def _build_rhc(state):
    sheet = state["sheet"]
    twp = state["township"]
    rhcs = gsheet_data.get_rhcs(sheet, twp)
    text = f"📊 <b>{sheet}</b>\n🏙 Township: <b>{twp}</b>\n\n🏥 RHC ရွေးချယ်ပါ:"
    kb = _paginated_buttons(rhcs, RHC_SELECT, state["page"], state["level"], PAGE_SIZE)
    return text, kb


def _build_subcenter(state):
    sheet = state["sheet"]
    twp = state["township"]
    rhc = state["rhc"]
    subs = gsheet_data.get_subcenters(sheet, twp, rhc)
    text = (
        f"📊 <b>{sheet}</b>\n"
        f"🏙 Township: <b>{twp}</b>\n"
        f"🏥 RHC: <b>{rhc}</b>\n\n"
        "🏘 Sub-center ရွေးချယ်ပါ:"
    )
    kb = _paginated_buttons(subs, SUBCENTER_SELECT, state["page"], state["level"], PAGE_SIZE_SMALL)
    return text, kb


def _build_village(state):
    sheet = state["sheet"]
    twp = state["township"]
    rhc = state["rhc"]
    sub = state["subcenter"]
    villages = gsheet_data.get_villages(sheet, twp, rhc, sub)
    text = (
        f"📊 <b>{sheet}</b>\n"
        f"🏙 Township: <b>{twp}</b>\n"
        f"🏥 RHC: <b>{rhc}</b>\n"
        f"🏘 Sub-center: <b>{sub}</b>\n\n"
        "🏡 Village ရွေးချယ်ပါ:"
    )
    kb = _paginated_buttons(villages, VILLAGE_SELECT, state["page"], state["level"], PAGE_SIZE_SMALL)
    return text, kb


def _build_month(state):
    sheet = state["sheet"]
    village = state["village"]
    text = (
        f"📊 <b>{sheet}</b>\n"
        f"🏡 Village: <b>{village}</b>\n\n"
        "📅 လ ရွေးချယ်ပါ:"
    )
    keyboard = []
    row = []
    for i, m in enumerate(MONTHS):
        row.append(InlineKeyboardButton(m[:3], callback_data=f"{MONTH_SELECT}:{m}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Stock sheet: Township Stock button
    if sheet == "Stock":
        keyboard.append([InlineKeyboardButton("🏙 Township Stock", callback_data=TOWNSHIP_STOCK_SELECT)])

    # Testing sheet: Yearly Total + Township Team Testing buttons
    if sheet == "Testing":
        keyboard.append([InlineKeyboardButton("📊 Yearly Total", callback_data=YEARLY_TOTAL_SELECT)])
        keyboard.append([InlineKeyboardButton("🏙 Township Team Testing", callback_data=TOWNSHIP_TESTING_SELECT)])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=BACK)])
    return text, InlineKeyboardMarkup(keyboard)


def _build_profile_data(state):
    try:
        data = gsheet_data.get_profile_data(
            state["township"], state["rhc"], state["subcenter"], state["village"]
        )
    except Exception:
        data = {}

    village = state["village"]
    text = f"📋 <b>Profile Data</b>\n🏡 Village: <b>{village}</b>\n\n"
    text += f"👤 Provider: <b>{data.get('Provider Name', 'N/A')}</b>\n"
    text += f"📞 Phone: <b>{data.get('Phone Contact', 'N/A')}</b>\n"
    text += f"🏠 HH: <b>{data.get('HH', 'N/A')}</b>\n"
    text += f"👥 Pop: <b>{data.get('Pop', 'N/A')}</b>\n"
    text += f"📍 Lat: <b>{data.get('Latitude', 'N/A')}</b>\n"
    text += f"📍 Long: <b>{data.get('Longitude', 'N/A')}</b>\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data=BACK)],
        [InlineKeyboardButton("❌ Close", callback_data=CLOSE)],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _build_monthly_data(state):
    sheet = state["sheet"]
    village = state["village"]
    month = state["month"]

    try:
        if sheet == "Stock":
            data = gsheet_data.get_stock_data(
                state["township"], state["rhc"], state["subcenter"], village, month
            )
            text = f"📦 <b>Stock Data</b>\n🏡 Village: <b>{village}</b>\n📅 Month: <b>{month}</b>\n\n"
            text += f"🔬 RDT: <b>{data.get('RDT', '-')}</b>\n"
            text += f"💊 ACT: <b>{data.get('ACT', '-')}</b>\n"
            text += f"💊 CQ: <b>{data.get('CQ', '-')}</b>\n"
            text += f"💊 PQ: <b>{data.get('PQ', '-')}</b>\n"
        else:
            data = gsheet_data.get_testing_data(
                state["township"], state["rhc"], state["subcenter"], village, month
            )
            text = f"🧪 <b>Testing Data</b>\n🏡 Village: <b>{village}</b>\n📅 Month: <b>{month}</b>\n\n"
            text += f"🔬 Testing: <b>{data.get('Testing', '-')}</b>\n"
            text += f"🦟 Pf: <b>{data.get('Pf', '-')}</b>\n"
            text += f"🦟 Pv: <b>{data.get('Pv', '-')}</b>\n"
            text += f"🦟 Mix: <b>{data.get('Mix', '-')}</b>\n"
            text += f"✅ NTG: <b>{data.get('NTG', '-')}</b>\n"
            text += f"🔄 Refer: <b>{data.get('Refer', '-')}</b>\n"
    except Exception:
        text = "⚠️ Data ရယူ၍မရပါ။"

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data=BACK)],
        [InlineKeyboardButton("❌ Close", callback_data=CLOSE)],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _build_yearly_data(state):
    village = state["village"]
    try:
        data = gsheet_data.get_testing_yearly_total(
            state["township"], state["rhc"], state["subcenter"], village
        )
    except Exception:
        data = {}

    text = f"📊 <b>Yearly Total - Testing</b>\n🏡 Village: <b>{village}</b>\n\n"
    text += f"🔬 Testing: <b>{data.get('Testing', '-')}</b>\n"
    text += f"🦟 Pf: <b>{data.get('Pf', '-')}</b>\n"
    text += f"🦟 Pv: <b>{data.get('Pv', '-')}</b>\n"
    text += f"🦟 Mix: <b>{data.get('Mix', '-')}</b>\n"
    text += f"✅ NTG: <b>{data.get('NTG', '-')}</b>\n"
    text += f"🔄 Refer: <b>{data.get('Refer', '-')}</b>\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data=BACK)],
        [InlineKeyboardButton("❌ Close", callback_data=CLOSE)],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _build_township_stock_data(state):
    """Display Township Stock totals – sums RDT/ACT/CQ/PQ across all villages in the township for each month."""
    township = state["township"]
    text = f"🏙 <b>Township Stock</b>\n🏙 Township: <b>{township}</b>\n\n"

    try:
        rows = [r for r in gsheet_data.stock_rows if r.get("Township") == township]
        if not rows:
            text += "⚠️ Data မရှိပါ။"
        else:
            for month in MONTHS:
                totals = {"RDT": 0, "ACT": 0, "CQ": 0, "PQ": 0}
                has_data = False
                for r in rows:
                    raw = r["_raw"]
                    for sub in totals:
                        col_idx = gsheet_data.stock_months.get((month, sub))
                        if col_idx is not None and col_idx < len(raw):
                            val = raw[col_idx].strip()
                            if val:
                                try:
                                    totals[sub] += int(val)
                                    has_data = True
                                except ValueError:
                                    pass
                if has_data:
                    text += (
                        f"📅 <b>{month}</b>: "
                        f"RDT={totals['RDT']}, ACT={totals['ACT']}, "
                        f"CQ={totals['CQ']}, PQ={totals['PQ']}\n"
                    )
    except Exception:
        text += "⚠️ Data ရယူ၍မရပါ။"

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data=BACK)],
        [InlineKeyboardButton("❌ Close", callback_data=CLOSE)],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _build_township_team_testing_data(state):
    """Display Township Team Testing totals – sums Testing/Pf/Pv/Mix/NTG/Refer across all villages in the township for each month."""
    township = state["township"]
    text = f"🏙 <b>Township Team Testing</b>\n🏙 Township: <b>{township}</b>\n\n"

    try:
        rows = [r for r in gsheet_data.testing_rows if r.get("Township") == township]
        if not rows:
            text += "⚠️ Data မရှိပါ။"
        else:
            subs = ["Testing", "Pf", "Pv", "Mix", "NTG", "Refer"]
            for month in MONTHS:
                totals = {s: 0 for s in subs}
                has_data = False
                for r in rows:
                    raw = r["_raw"]
                    for sub in subs:
                        col_idx = gsheet_data.testing_months.get((month, sub))
                        if col_idx is not None and col_idx < len(raw):
                            val = raw[col_idx].strip()
                            if val:
                                try:
                                    totals[sub] += int(val)
                                    has_data = True
                                except ValueError:
                                    pass
                if has_data:
                    text += (
                        f"📅 <b>{month}</b>: "
                        f"Testing={totals['Testing']}, Pf={totals['Pf']}, "
                        f"Pv={totals['Pv']}, Mix={totals['Mix']}, "
                        f"NTG={totals['NTG']}, Refer={totals['Refer']}\n"
                    )

            # Yearly Total
            yearly_totals = {s: 0 for s in subs}
            yearly_has = False
            for r in rows:
                raw = r["_raw"]
                for sub in subs:
                    col_idx = gsheet_data.testing_months.get(("Yearly Total", sub))
                    if col_idx is not None and col_idx < len(raw):
                        val = raw[col_idx].strip()
                        if val:
                            try:
                                yearly_totals[sub] += int(val)
                                yearly_has = True
                            except ValueError:
                                pass
            if yearly_has:
                text += (
                    f"\n📊 <b>Yearly Total</b>: "
                    f"Testing={yearly_totals['Testing']}, Pf={yearly_totals['Pf']}, "
                    f"Pv={yearly_totals['Pv']}, Mix={yearly_totals['Mix']}, "
                    f"NTG={yearly_totals['NTG']}, Refer={yearly_totals['Refer']}\n"
                )
    except Exception:
        text += "⚠️ Data ရယူ၍မရပါ။"

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data=BACK)],
        [InlineKeyboardButton("❌ Close", callback_data=CLOSE)],
    ]
    return text, InlineKeyboardMarkup(keyboard)


# ─── PAGINATION HELPER ──────────────────────────────────────

def _paginated_buttons(items, action_prefix, page, current_level, page_size=PAGE_SIZE):
    start = page * page_size
    end = start + page_size
    page_items = items[start:end]
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    current_page_num = page + 1

    keyboard = [[InlineKeyboardButton(item, callback_data=f"{action_prefix}:{item}")] for item in page_items]

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"{PAGE}:{page - 1}:{current_level}"))
    if end < len(items):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{PAGE}:{page + 1}:{current_level}"))
    if nav_row:
        keyboard.append(nav_row)

    # Show page indicator if there are multiple pages
    if total_pages > 1:
        keyboard.append([InlineKeyboardButton(f"📄 {current_page_num}/{total_pages}", callback_data="noop")])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=BACK)])
    return InlineKeyboardMarkup(keyboard)


# ─── AUTO-DELETE / SCHEDULING ───────────────────────────────

def _schedule_deletion(context, chat_id, message_id, user_id):
    """Schedule auto-deletion of a message. Safely skips if job_queue is not available."""
    if context.job_queue is None:
        logger.warning("job_queue is None – auto-delete scheduling skipped.")
        return
    job_name = f"del_{user_id}"
    context.job_queue.run_once(
        _delete_callback,
        MESSAGE_TIMEOUT,
        data={"chat_id": chat_id, "message_id": message_id, "user_id": user_id},
        name=job_name,
    )


def _remove_scheduled(context, user_id):
    """Remove any pending auto-delete job. Safely skips if job_queue is not available."""
    if context.job_queue is None:
        logger.warning("job_queue is None – scheduled job removal skipped.")
        return
    job_name = f"del_{user_id}"
    jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in jobs:
        job.schedule_removal()


def _reschedule(context, chat_id, state, user_id):
    if "message_id" in state:
        _remove_scheduled(context, user_id)
        _schedule_deletion(context, chat_id, state["message_id"], user_id)


async def _delete_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    chat_id = data["chat_id"]
    message_id = data["message_id"]
    user_id = data["user_id"]
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        if user_id in user_states:
            del user_states[user_id]
        logger.info(f"Auto-deleted message {message_id} for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")


async def _cleanup_old_message(context, user_id, chat_id):
    if user_id in user_states:
        old_state = user_states[user_id]
        old_msg_id = old_state.get("message_id")
        if old_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
            except Exception:
                pass
        _remove_scheduled(context, user_id)


# ─── NOOP HANDLER (for page indicator button) ───────────────

async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle noop callback data – does nothing, just answers the callback."""
    query = update.callback_query
    await query.answer()


# ─── ERROR HANDLER ──────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and prevent unhandled exception noise in logs."""
    logger.error("Exception while handling an update:", exc_info=context.error)


# ─── MAIN ───────────────────────────────────────────────────

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check_data", check_data))
    # Handle noop callback (page indicator) separately so it doesn't go through button()
    application.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"))
    application.add_handler(CallbackQueryHandler(button))

    # Register error handler to suppress noisy tracebacks in logs
    application.add_error_handler(error_handler)

    # Start keep_alive for Render
    try:
        keep_alive()
    except Exception:
        pass

    print("✅ Data Viewer Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
