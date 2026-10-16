
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.main import main_keyboard

router = Router(name="start")


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()

    await message.answer(
        "🐙 Welcome to GitHub Bot!\n\n"
        "Send a GitHub repository link at any time to open it, "
        "or choose an option below.",
        reply_markup=main_keyboard(),
    )
