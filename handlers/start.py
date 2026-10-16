from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards.main import main_keyboard


router = Router(name="start")


@router.message(CommandStart())
async def start_handler(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    await message.answer(
        "Welcome!\n\n"
        "Choose a service to get started.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text == "🔎 Search GitHub")
async def search_button_handler(
    message: Message,
    state: FSMContext,
):
    await state.set_state("waiting_for_repository_query")

    await message.answer(
        "Enter a GitHub repository name, search query, "
        "or repository URL."
    )
