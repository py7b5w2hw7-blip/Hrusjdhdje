import asyncio
import sqlite3
import os
import logging
from datetime import datetime, date
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------- LOAD ENV ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("Проверь .env файл!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------------- DB ----------------
def get_db():
    return sqlite3.connect("bot.db", check_same_thread=False)

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        banned INTEGER DEFAULT 0,
        username TEXT,
        first_name TEXT,
        joined_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        time TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        time TEXT
    )
    """)
    db.commit()
    db.close()

init_db()

# ---------------- DB HELPERS ----------------
def add_user(uid: int, username: str = None, first_name: str = None):
    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
    """, (uid, username, first_name, datetime.now().isoformat()))
    db.commit()
    db.close()

def is_banned(uid: int) -> bool:
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    db.close()
    return r and r[0] == 1

def log_visit(uid: int):
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO visits (user_id, time) VALUES (?, ?)",
                (uid, datetime.now().isoformat()))
    db.commit()
    db.close()

def log_payment(uid: int, amount: int):
    db = get_db()
    cur = db.cursor()
    cur.execute("INSERT INTO stats (user_id, amount, time) VALUES (?, ?, ?)",
                (uid, amount, datetime.now().isoformat()))
    db.commit()
    db.close()

def get_today_stats():
    d = date.today().isoformat()
    db = get_db()
    cur = db.cursor()
    money = cur.execute("SELECT COALESCE(SUM(amount), 0) FROM stats WHERE date(time)=?", (d,)).fetchone()[0]
    visits = cur.execute("SELECT COUNT(*) FROM visits WHERE date(time)=?", (d,)).fetchone()[0]
    db.close()
    return money, visits

# ---------------- PAYMENT ----------------
async def send_stars_payment(user_id: int, amount: int):
    try:
        invoice_link = await bot.create_invoice_link(
            title="Пополнение Stars",
            description=f"Покупка {amount} ⭐",
            payload=f"pay_{amount}_{int(datetime.now().timestamp())}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Stars", amount=amount)]
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💎 Оплатить {amount} ⭐", url=invoice_link)]
        ])

        await bot.send_message(
            chat_id=user_id,
            text=f"Подтверждение покупки\n\nВы хотите приобрести **{amount} ⭐**?",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await bot.send_message(user_id, "❌ Ошибка создания оплаты.")

# ---------------- KEYBOARDS ----------------
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить Stars", callback_data="buy_stars")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🔗 Получить ссылки", callback_data="get_links")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="ban_menu")],
    ])

# ---------------- HANDLERS ----------------
@dp.message(F.text.startswith("/start"))
async def start(m: Message):
    uid = m.from_user.id
    add_user(uid, m.from_user.username, m.from_user.first_name)

    if is_banned(uid):
        await m.answer("Вы заблокированы.")
        return

    log_visit(uid)

    parts = m.text.split()
    if len(parts) > 1 and parts[1].isdigit():
        amount = int(parts[1])
        if amount in [350, 450, 600, 950]:
            await send_stars_payment(uid, amount)
            return

    if uid == ADMIN_ID:
        await m.answer("👑 Админ панель", reply_markup=admin_menu())
    else:
        await m.answer("Добро пожаловать!\n\nВыберите действие 👇", reply_markup=main_menu())


@dp.callback_query(F.data == "buy_stars")
async def buy_stars_callback(c: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="350 ⭐", callback_data="pay_350")],
        [InlineKeyboardButton(text="450 ⭐", callback_data="pay_450")],
        [InlineKeyboardButton(text="600 ⭐", callback_data="pay_600")],
        [InlineKeyboardButton(text="950 ⭐", callback_data="pay_950")],
    ])
    await c.message.edit_text("💎 Выберите сумму:", reply_markup=kb)


@dp.callback_query(F.data.startswith("pay_"))
async def process_payment(c: CallbackQuery):
    amount = int(c.data.split("_")[1])
    await c.answer()
    await send_stars_payment(c.from_user.id, amount)


# ---------------- ПРЯМЫЕ ССЫЛКИ ----------------
@dp.callback_query(F.data == "get_links")
async def get_links_callback(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа")
        return

    amounts = [350, 450, 600, 950]
    text = "🔗 **Прямые ссылки для оплаты:**\n\n"

    for amount in amounts:
        try:
            link = await bot.create_invoice_link(
                title="Пополнение Stars",
                description=f"Покупка {amount} ⭐",
                payload=f"pay_{amount}_{int(datetime.now().timestamp())}",
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label="Stars", amount=amount)]
            )
            text += f"💎 {amount} ⭐ — [Оплатить {amount} ⭐]({link})\n\n"
        except Exception as e:
            text += f"{amount} ⭐ — ошибка\n"
    
    await c.message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(q.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(m: Message):
    uid = m.from_user.id
    amount = m.successful_payment.total_amount

    log_payment(uid, amount)

    await bot.send_message(
        ADMIN_ID,
        f"💰 НОВАЯ ОПЛАТА!\nID: {uid}\nИмя: {m.from_user.full_name}\nСумма: {amount} ⭐"
    )
    await m.answer(f"✅ Успешно! Начислено {amount} ⭐")


# ---------------- ADMIN ----------------
@dp.message(F.text == "/admin")
async def admin_panel(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    await m.answer("👑 Админ панель", reply_markup=admin_menu())


@dp.callback_query(F.data == "stats")
async def stats_callback(c: CallbackQuery):
    money, visits = get_today_stats()
    await c.message.answer(f"📊 Сегодня\n💰 {money} ⭐\n👥 {visits} посещений")


@dp.callback_query(F.data == "ban_menu")
async def ban_menu(c: CallbackQuery):
    await c.message.answer("Отправьте:\n`/ban <user_id>`", parse_mode="Markdown")


@dp.message(F.text.startswith("/ban "))
async def ban_user(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(m.text.split()[1])
        db = get_db()
        cur = db.cursor()
        cur.execute("UPDATE users SET banned=1 WHERE user_id=?", (uid,))
        db.commit()
        db.close()
        await m.answer(f"✅ {uid} забанен")
    except:
        await m.answer("❌ Неверный формат")


# ---------------- RUN ----------------
async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())