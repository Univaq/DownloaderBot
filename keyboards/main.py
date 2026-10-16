from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🐙 GitHub"),
            ],
            [
                KeyboardButton(text="▶️ YouTube Downloader"),
                KeyboardButton(text="📸 Instagram Downloader"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose a service...",
    )


def github_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔎 Search GitHub"),
            ],
            [
                KeyboardButton(text="⭐ Favorites"),
                KeyboardButton(text="🕘 Search History"),
            ],
            [
                KeyboardButton(text="⬅️ Main Menu"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose a GitHub option...",
    )
