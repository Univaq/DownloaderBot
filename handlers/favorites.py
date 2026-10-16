
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from repositories.jobs import (
    add_favorite,
    get_favorites,
    is_favorite,
    remove_favorite,
)
from services.callback_cache import (
    get_repository,
    store_repository,
)
from keyboards.inline import repository_action_keyboard

router = Router(name="favorites")


@router.callback_query(F.data.startswith("favorite:add:"))
async def add_favorite_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        await callback.answer("Invalid request.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:add:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "Repository session expired. Open the repository again.",
            show_alert=True,
        )
        return

    result = await add_favorite(callback.from_user.id, full_name)

    if result == "full":
        await callback.answer(
            "Favorites is full (20 repositories). Remove one first.",
            show_alert=True,
        )
        return

    if result == "exists":
        await callback.answer("Already in Favorites ⭐")
    else:
        await callback.answer("Added to Favorites ⭐")

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=repository_action_keyboard(
                full_name,
                is_favorite=True,
            )
        )


@router.message(F.text == "⭐ Favorites")
async def show_favorites(message: Message) -> None:
    if not message.from_user:
        return

    favorites = await get_favorites(message.from_user.id)

    if not favorites:
        await message.answer(
            "⭐ Your Favorites list is empty.\n"
            "Open a repository and press ⭐ Add to Favorites."
        )
        return

    builder = InlineKeyboardBuilder()

    for full_name in favorites[:20]:
        repository_id = store_repository(full_name)

        builder.button(
            text=f"📦 {full_name}"[:60],
            callback_data=f"favorite:open:{repository_id}",
        )

    builder.adjust(1)

    await message.answer(
        "⭐ <b>Your Favorites</b>\n\n"
        "Select a repository to open its action menu.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("favorite:open:"))
async def open_favorite_handler(callback: CallbackQuery) -> None:
    if not callback.data:
        await callback.answer("Invalid request.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:open:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "Repository session expired. Open Favorites again.",
            show_alert=True,
        )
        return

    await callback.answer()

    if callback.message:
        favorite_status = await is_favorite(
            callback.from_user.id,
            full_name,
        ) if callback.from_user else False

        await callback.message.answer(
            f"📦 <b>{full_name}</b>\n\n"
            "Choose what you want to download:",
            reply_markup=repository_action_keyboard(
                full_name,
                is_favorite=favorite_status,
            ),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("favorite:remove:"))
async def remove_favorite_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        await callback.answer("Invalid request.", show_alert=True)
        return

    repository_id = callback.data.removeprefix("favorite:remove:")
    full_name = get_repository(repository_id)

    if not full_name:
        await callback.answer(
            "Repository session expired. Open the repository again.",
            show_alert=True,
        )
        return

    removed = await remove_favorite(callback.from_user.id, full_name)

    if not removed:
        await callback.answer("Repository was not in your Favorites.")
        return

    await callback.answer("Removed from Favorites.")

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=repository_action_keyboard(
                full_name,
                is_favorite=False,
            )
        )