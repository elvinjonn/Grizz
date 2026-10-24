import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_USERNAME = "@grizzcardd"
CHANNEL_URL = "https://t.me/grizzcardd"
ADMIN = "@zntgrizz"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

BUY_TEXT = f"Skidka narxda sotib olish uchun {ADMIN}"


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        )
    except Exception as e:
        logging.warning("Obuna tekshirishda xato: %s", e)
        return False


def sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Tekshirish", callback_data="check")],
        ]
    )


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 SKINHACK", callback_data="skinhack")],
            [InlineKeyboardButton(text="👨‍💻 ADMIN BILAN MUROJAAT", callback_data="admin")],
        ]
    )


def phone_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍎 iOS", callback_data="ios"),
                InlineKeyboardButton(text="🤖 Android", callback_data="android"),
            ]
        ]
    )


async def send_menu(message: Message, name: str):
    await message.answer(
        f"Assalomu alaykum, {name}! 👋\nBotimizga xush kelibsiz.\n\nBo'limni tanlang:",
        reply_markup=menu_kb(),
    )


@dp.message(CommandStart())
async def start(message: Message):
    name = message.from_user.full_name
    if await is_subscribed(message.from_user.id):
        await send_menu(message, name)
    else:
        await message.answer(
            f"Assalomu alaykum, {name}! 👋\n\nBotdan foydalanish uchun avval kanalimizga obuna bo'ling:",
            reply_markup=sub_kb(),
        )


@dp.callback_query(F.data == "check")
async def check(call: CallbackQuery):
    if await is_subscribed(call.from_user.id):
        await call.message.delete()
        await send_menu(call.message, call.from_user.full_name)
        await call.answer()
    else:
        await call.answer("❌ Siz hali obuna bo'lmagansiz!", show_alert=True)


async def guard(call: CallbackQuery) -> bool:
    if await is_subscribed(call.from_user.id):
        return True
    await call.message.answer(
        "Avval kanalimizga obuna bo'ling:", reply_markup=sub_kb()
    )
    await call.answer()
    return False


@dp.callback_query(F.data == "skinhack")
async def skinhack(call: CallbackQuery):
    if not await guard(call):
        return
    await call.message.answer("Telefoningiz qanday? 📱", reply_markup=phone_kb())
    await call.answer()


@dp.callback_query(F.data.in_({"ios", "android"}))
async def phone_chosen(call: CallbackQuery):
    if not await guard(call):
        return
    await call.message.answer(BUY_TEXT)
    await call.answer()


@dp.callback_query(F.data == "admin")
async def admin(call: CallbackQuery):
    if not await guard(call):
        return
    await call.message.answer(f"Admin bilan murojaat: {ADMIN}")
    await call.answer()


async def health(_):
    return web.Response(text="OK")


async def main():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000)))
    await site.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
