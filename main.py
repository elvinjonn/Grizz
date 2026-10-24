import asyncio
import copy
import html
import json
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton as B,
    InlineKeyboardMarkup as KB,
    Message,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_ID", "").split(",") if x.strip()}
CHANNEL_USERNAME = "@grizzcardd"
CHANNEL_URL = "https://t.me/grizzcardd"
ADMIN_USERNAME = "@zntgrizz"
PRICE = "80 000 so'm"
REQUIRE_SUB = False  # majburiy obuna o'chirilgan. Yoqish uchun True qiling

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ---------------------------------------------------------------- storage
DEFAULT = {
    "users": {},
    "videos": [],
    "files": {},
    "card": "💳 <code>9860160120687738</code>\n👤 U.sh",
}

# iOS versiyalar ro'yxati (kerak bo'lsa shu yerda o'zgartiring)
IOS_VERSIONS = ["18", "26", "26.1", "26.2", "26.3", "26.4", "27", "27.1"]

# UC narxlari (UC, so'm). Kerak bo'lsa shu yerda o'zgartiring
UC_PRICES = [
    (60, 13000), (120, 26000), (180, 39000), (240, 52000), (325, 60000),
    (385, 73000), (445, 86000), (505, 99000), (660, 117000), (720, 130000),
    (840, 156000), (985, 177000), (1105, 203000), (1320, 234000), (1500, 273000),
    (1800, 300000), (1920, 325000), (2120, 360000), (2460, 417000), (2785, 477000),
    (3850, 580000), (4510, 700000), (4835, 760000), (5650, 905000), (6310, 1000000),
    (8100, 1130000), (16200, 2260000),
]


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


data: dict = {}
mongo_col = None

waiting_check: dict[int, dict] = {}
waiting_uc_id: dict[int, dict] = {}
admin_state: dict[int, tuple] = {}


async def load():
    global data, mongo_col
    url = os.environ.get("MONGO_URL")
    if url:
        from motor.motor_asyncio import AsyncIOMotorClient

        mongo_col = AsyncIOMotorClient(url)["grizzbot"]["state"]
        data = await mongo_col.find_one({"_id": "main"}) or {}
    elif os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            data = json.load(f)
    for k, v in DEFAULT.items():
        data.setdefault(k, copy.deepcopy(v))


async def save():
    if mongo_col is not None:
        await mongo_col.replace_one({"_id": "main"}, {**data, "_id": "main"}, upsert=True)
    else:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def has_cert(uid: int) -> bool:
    return data["users"].get(str(uid), {}).get("cert", False)


async def send_item(chat_id: int, item: dict, caption: str | None = None):
    t, fid = item["type"], item["id"]
    if t == "video":
        await bot.send_video(chat_id, fid, caption=caption)
    elif t == "photo":
        await bot.send_photo(chat_id, fid, caption=caption)
    else:
        await bot.send_document(chat_id, fid, caption=caption)


def extract(m: Message) -> dict | None:
    if m.video:
        return {"type": "video", "id": m.video.file_id}
    if m.document:
        return {"type": "document", "id": m.document.file_id}
    if m.photo:
        return {"type": "photo", "id": m.photo[-1].file_id}
    return None


# ---------------------------------------------------------------- keyboards
def sub_kb():
    return KB(
        inline_keyboard=[
            [B(text="📢 Kanalga obuna bo'lish", url=CHANNEL_URL)],
            [B(text="✅ Tekshirish", callback_data="check")],
        ]
    )


def menu_kb():
    return KB(
        inline_keyboard=[
            [B(text="📜 Sertifikat olish", callback_data="cert")],
            [B(text="💎 UC sotib olish", callback_data="uc")],
            [B(text="🎮 SKINHACK", callback_data="skinhack")],
            [B(text="👨‍💻 ADMIN BILAN MUROJAAT", callback_data="admin")],
        ]
    )


def platform_kb():
    return KB(
        inline_keyboard=[
            [
                B(text="🍎 iOS", callback_data="plat:ios"),
                B(text="🤖 Android", callback_data="plat:android"),
            ]
        ]
    )


def ios_versions_kb():
    btns = [B(text=f"iOS {v}", callback_data=f"iosv:{v}") for v in IOS_VERSIONS]
    rows = [btns[i : i + 3] for i in range(0, len(btns), 3)]
    return KB(inline_keyboard=rows)


def dl_kb(cb: str):
    return KB(inline_keyboard=[[B(text="⬇️ Skinhackni yuklash", callback_data=cb)]])


def cert_kb():
    return KB(inline_keyboard=[[B(text="✅ To'lov qildim", callback_data="paid")]])


# ---------------------------------------------------------------- subscription
async def is_subscribed(uid: int) -> bool:
    if not REQUIRE_SUB:
        return True
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, uid)
        return m.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        )
    except Exception as e:
        logging.warning("Obuna tekshirishda xato: %s", e)
        return False


async def guard(call: CallbackQuery) -> bool:
    if await is_subscribed(call.from_user.id):
        return True
    await call.message.answer("Avval kanalimizga obuna bo'ling:", reply_markup=sub_kb())
    await call.answer()
    return False


async def send_menu(message: Message, name: str):
    await message.answer(
        f"Assalomu alaykum, {html.escape(name)}! 👋\nBotimizga xush kelibsiz.\n\nBo'limni tanlang:",
        reply_markup=menu_kb(),
    )


# ---------------------------------------------------------------- user handlers
@dp.message(CommandStart())
async def start(message: Message):
    u = message.from_user
    data["users"].setdefault(str(u.id), {"cert": False})["name"] = u.full_name
    await save()
    if await is_subscribed(u.id):
        await send_menu(message, u.full_name)
    else:
        await message.answer(
            f"Assalomu alaykum, {html.escape(u.full_name)}! 👋\n\n"
            "Botdan foydalanish uchun avval kanalimizga obuna bo'ling:",
            reply_markup=sub_kb(),
        )


@dp.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Sizning ID: <code>{message.from_user.id}</code>")


@dp.callback_query(F.data == "check")
async def check(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.delete()
        await send_menu(call.message, call.from_user.full_name)
        await call.answer()
    else:
        await call.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)


@dp.callback_query(F.data == "admin")
async def admin_contact(call: CallbackQuery):
    if not await guard(call):
        return
    await call.message.answer(f"Muammo bormi? {ADMIN_USERNAME} ga yozing.")
    await call.answer()


# ---- sertifikat
@dp.callback_query(F.data == "cert")
async def cert(call: CallbackQuery):
    if not await guard(call):
        return
    if has_cert(call.from_user.id):
        await call.message.answer("✅ Sizda sertifikat allaqachon bor.")
    else:
        await call.message.answer(
            f"📜 Sertifikat narxi: <b>{PRICE}</b>\n\n"
            f"💳 To'lov uchun:\n{data['card']}\n\n"
            "To'lovni qilgach, «✅ To'lov qildim» tugmasini bosing.",
            reply_markup=cert_kb(),
        )
    await call.answer()


@dp.callback_query(F.data == "paid")
async def paid(call: CallbackQuery):
    if not await guard(call):
        return
    waiting_check[call.from_user.id] = {"kind": "cert"}
    await call.message.answer("📸 Iltimos, to'lov chekini (rasm yoki skrinshot) yuboring.")
    await call.answer()


# ---- UC
@dp.callback_query(F.data == "uc")
async def uc_menu(call: CallbackQuery):
    if not await guard(call):
        return
    btns = [B(text=f"{uc} UC — {fmt(p)}", callback_data=f"ucp:{uc}") for uc, p in UC_PRICES]
    rows = [btns[i : i + 2] for i in range(0, len(btns), 2)]
    await call.message.answer("💎 Kerakli UC miqdorini tanlang:", reply_markup=KB(inline_keyboard=rows))
    await call.answer()


@dp.callback_query(F.data.startswith("ucp:"))
async def uc_pick(call: CallbackQuery):
    if not await guard(call):
        return
    uc = int(call.data.split(":")[1])
    price = dict(UC_PRICES).get(uc)
    if not price:
        return await call.answer()
    await call.message.answer(
        f"💎 <b>{uc} UC</b>\n💰 Narxi: <b>{fmt(price)} so'm</b>\n\n"
        f"💳 To'lov uchun:\n{data['card']}\n\n"
        "To'lovni qilgach, «✅ To'lov qildim» tugmasini bosing.",
        reply_markup=KB(inline_keyboard=[[B(text="✅ To'lov qildim", callback_data=f"ucpaid:{uc}")]]),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("ucpaid:"))
async def uc_paid(call: CallbackQuery):
    if not await guard(call):
        return
    uc = int(call.data.split(":")[1])
    price = dict(UC_PRICES).get(uc)
    if not price:
        return await call.answer()
    waiting_uc_id[call.from_user.id] = {"uc": uc, "price": price}
    await call.message.answer("🎮 PUBG Mobile ID raqamingizni yuboring (faqat raqamlar).")
    await call.answer()


# ---- skinhack
@dp.callback_query(F.data == "skinhack")
async def skinhack(call: CallbackQuery):
    if not await guard(call):
        return
    await call.message.answer("Telefoningiz qanday? 📱", reply_markup=platform_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("plat:"))
async def platform(call: CallbackQuery):
    if not await guard(call):
        return
    plat = call.data.split(":")[1]
    if plat == "ios":
        await call.message.answer("iOS versiyangiz qanaqa? 👇", reply_markup=ios_versions_kb())
    else:
        await call.message.answer("Android tanlandi 🤖", reply_markup=dl_kb("dl:android"))
    await call.answer()


@dp.callback_query(F.data.startswith("iosv:"))
async def ios_version(call: CallbackQuery):
    if not await guard(call):
        return
    v = call.data.split(":")[1]
    await call.message.answer(f"iOS {v} tanlandi 🍎", reply_markup=dl_kb(f"dl:ios:{v}"))
    await call.answer()


@dp.callback_query(F.data.startswith("dl:"))
async def download(call: CallbackQuery):
    if not await guard(call):
        return
    uid = call.from_user.id
    if not has_cert(uid):
        await call.message.answer(
            "⚠️ Avval sertifikat oling, keyin faylni qo'lga kirita olasiz.",
            reply_markup=KB(inline_keyboard=[[B(text="📜 Sertifikat olish", callback_data="cert")]]),
        )
        await call.answer()
        return
    parts = call.data.split(":")
    plat = parts[1]
    key = f"{plat}_{parts[2]}" if plat == "ios" else plat
    item = data["files"].get(key)
    if not item and plat == "ios":
        major = parts[2].split(".")[0]
        item = data["files"].get(f"ios_{major}")
    item = item or data["files"].get(plat)
    if item:
        await send_item(uid, item)
    else:
        await call.message.answer(f"Fayl hali yuklanmagan. {ADMIN_USERNAME} ga yozing.")
    await call.answer()


# ---------------------------------------------------------------- media (chek / admin yuklash)
@dp.message(F.photo | F.document | F.video)
async def media(message: Message):
    uid = message.from_user.id
    item = extract(message)

    if is_admin(uid):
        st = admin_state.get(uid)
        if not st or not item:
            return
        if st[0] == "videos":
            data["videos"].append(item)
            await save()
            await message.answer(f"✅ Qo'shildi. Jami: {len(data['videos'])}. Tugatish: /done")
        elif st[0] == "file":
            data["files"][st[1]] = item
            admin_state.pop(uid, None)
            await save()
            await message.answer(f"✅ Fayl saqlandi: <code>{st[1]}</code>")
        return

    if uid in waiting_check:
        ctx = waiting_check.pop(uid)
        u = message.from_user
        uname = f"@{u.username}" if u.username else "yo'q"
        if ctx["kind"] == "uc":
            prefix = "u"
            caption = (
                f"💎 <b>UC buyurtma</b>\n👤 {html.escape(u.full_name)} ({uname})\n🆔 <code>{uid}</code>\n"
                f"📦 {ctx['uc']} UC\n💰 {fmt(ctx['price'])} so'm\n🎮 PUBG ID: <code>{ctx['pubg']}</code>"
            )
        else:
            prefix = ""
            caption = (
                f"💳 <b>Sertifikat cheki</b>\n👤 {html.escape(u.full_name)} ({uname})\n🆔 <code>{uid}</code>\n"
                f"💰 {PRICE}"
            )
        kb = KB(
            inline_keyboard=[
                [
                    B(text="✅ Tasdiqlash", callback_data=f"{prefix}ok:{uid}"),
                    B(text="❌ Rad etish", callback_data=f"{prefix}no:{uid}"),
                ]
            ]
        )
        sent = False
        for a in ADMIN_IDS:
            try:
                await message.copy_to(a, caption=caption, reply_markup=kb)
                sent = True
            except Exception as e:
                logging.warning("Adminga yuborilmadi (%s): %s", a, e)
        if sent:
            await message.answer("✅ Chek adminga yuborildi. Tasdiqlanishini kuting.")
        else:
            await message.answer(f"Xatolik. Iltimos {ADMIN_USERNAME} ga yozing.")


# ---------------------------------------------------------------- admin: tasdiqlash
@dp.callback_query(F.data.startswith("ok:"))
async def approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = int(call.data.split(":")[1])
    data["users"].setdefault(str(uid), {})["cert"] = True
    await save()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ {uid} tasdiqlandi.")
    await call.answer()
    try:
        await bot.send_message(
            uid,
            "✅ To'lovingiz tasdiqlandi! Sertifikat faol.\n"
            "Pastda sertifikat olish bo'yicha qo'llanmalar 👇",
        )
        for v in data["videos"]:
            await send_item(uid, v)
        await bot.send_message(uid, "Endi 🎮 SKINHACK bo'limidan foydalanishingiz mumkin. /start")
    except Exception as e:
        logging.warning("Foydalanuvchiga yuborilmadi: %s", e)


@dp.callback_query(F.data.startswith("no:"))
async def reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ {uid} rad etildi.")
    await call.answer()
    try:
        await bot.send_message(
            uid, f"❌ To'lov tasdiqlanmadi. Muammo bo'lsa {ADMIN_USERNAME} ga yozing."
        )
    except Exception as e:
        logging.warning("Foydalanuvchiga yuborilmadi: %s", e)


@dp.callback_query(F.data.startswith("uok:"))
async def uc_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ {uid} UC buyurtmasi tasdiqlandi. UC ni tushirib bering.")
    await call.answer()
    try:
        await bot.send_message(
            uid, "✅ To'lovingiz tasdiqlandi! UC tez orada hisobingizga tushiriladi. 💎"
        )
    except Exception as e:
        logging.warning("Foydalanuvchiga yuborilmadi: %s", e)


@dp.callback_query(F.data.startswith("uno:"))
async def uc_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = int(call.data.split(":")[1])
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ {uid} UC buyurtmasi rad etildi.")
    await call.answer()
    try:
        await bot.send_message(
            uid, f"❌ To'lov tasdiqlanmadi. Muammo bo'lsa {ADMIN_USERNAME} ga yozing."
        )
    except Exception as e:
        logging.warning("Foydalanuvchiga yuborilmadi: %s", e)


# ---------------------------------------------------------------- admin buyruqlari
@dp.message(Command("admin"))
async def admin_help(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>Admin buyruqlari:</b>\n"
        "/setcard <i>matn</i> — to'lov karta ma'lumoti\n"
        "/addvideo — qo'llanma videolarini qo'shish (tugatish: /done)\n"
        "/clearvideos — videolarni tozalash\n"
        "/setios <i>26</i> — shu iOS versiya uchun fayl yuklash\n"
        "/setios — barcha iOS versiyalar uchun umumiy fayl\n"
        "/setandroid — Android fayli\n"
        "/stats — statistika"
    )


@dp.message(Command("setcard"))
async def setcard(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id) or not command.args:
        return
    data["card"] = command.args
    await save()
    await message.answer("✅ Karta ma'lumoti saqlandi.")


@dp.message(Command("addvideo"))
async def addvideo(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_state[message.from_user.id] = ("videos",)
    await message.answer("Videolarni yuboring. Tugagach /done bosing.")


@dp.message(Command("done"))
async def done(message: Message):
    if is_admin(message.from_user.id):
        admin_state.pop(message.from_user.id, None)
        await message.answer("✅ Tayyor.")


@dp.message(Command("clearvideos"))
async def clearvideos(message: Message):
    if is_admin(message.from_user.id):
        data["videos"] = []
        await save()
        await message.answer("🗑 Videolar tozalandi.")


@dp.message(Command("setios"))
async def setios(message: Message, command: CommandObject):
    if not is_admin(message.from_user.id):
        return
    v = (command.args or "").strip()
    key = f"ios_{v}" if v else "ios"
    admin_state[message.from_user.id] = ("file", key)
    await message.answer(f"Endi faylni yuboring (<code>{key}</code>).")


@dp.message(Command("setandroid"))
async def setandroid(message: Message):
    if not is_admin(message.from_user.id):
        return
    admin_state[message.from_user.id] = ("file", "android")
    await message.answer("Endi Android faylini yuboring.")


@dp.message(Command("stats"))
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users = data["users"]
    certs = sum(1 for u in users.values() if u.get("cert"))
    await message.answer(
        f"👥 Foydalanuvchilar: {len(users)}\n📜 Sertifikatli: {certs}\n"
        f"🎬 Videolar: {len(data['videos'])}\n📁 Fayllar: {', '.join(data['files']) or '—'}"
    )


@dp.message(F.text & ~F.text.startswith("/"))
async def text_in(message: Message):
    uid = message.from_user.id
    ctx = waiting_uc_id.get(uid)
    if not ctx:
        return
    pubg = message.text.strip()
    if not pubg.isdigit() or not (5 <= len(pubg) <= 15):
        await message.answer("❌ ID faqat raqamlardan iborat bo'lishi kerak. Qayta yuboring.")
        return
    waiting_uc_id.pop(uid)
    waiting_check[uid] = {"kind": "uc", "uc": ctx["uc"], "price": ctx["price"], "pubg": pubg}
    await message.answer("📸 Endi to'lov chekini (rasm yoki skrinshot) yuboring.")


# ---------------------------------------------------------------- web (UptimeRobot) + run
async def health(_):
    return web.Response(text="OK")


async def main():
    await load()
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000))).start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
