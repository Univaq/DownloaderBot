from aiogram import F, Router
from aiogram.types import Message

from keyboards.main import main_keyboard, github_keyboard


router = Router(name="menu")


@router.message(F.text == "🐙 GitHub")
async def open_github_menu(message: Message) -> None:
    await message.answer(
        "🐙 <b>GitHub</b>\n\nChoose an option:",
        reply_markup=github_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "⬅️ Main Menu")
async def back_to_main_menu(message: Message) -> None:
    await message.answer(
        "🏠 <b>Main Menu</b>\n\nChoose a service:",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text.in_({
    "▶️ YouTube Downloader",
    "📸 Instagram Downloader",
}))
async def coming_soon(message: Message) -> None:
    await message.answer("🚧 This feature is coming soon.")
