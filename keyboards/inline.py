
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.callback_cache import (
    store_repository,
    store_release,
    link_repository_to_search,
    get_repository_search,
)

CALLBACK_MAX_BYTES = 64
MAX_BUTTON_TEXT_LENGTH = 60
MAX_REPOSITORIES = 10
MAX_RELEASES = 10


def _validate_callback_data(callback_data: str) -> str:
    if len(callback_data.encode("utf-8")) > CALLBACK_MAX_BYTES:
        raise ValueError(
            "Callback data exceeds Telegram's 64-byte limit."
        )
    return callback_data


def add_back_button(builder, callback_data: str):
    builder.button(
        text="⬅️ Back",
        callback_data=_validate_callback_data(callback_data),
    )


def repository_keyboard(repositories, search_token: str):
    builder = InlineKeyboardBuilder()

    for repo in repositories[:MAX_REPOSITORIES]:
        full_name = repo["full_name"]
        repository_id = store_repository(full_name)

        link_repository_to_search(repository_id, search_token)

        builder.button(
            text=f"📦 {full_name}"[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"repo:{repository_id}"
            ),
        )

    builder.adjust(1)
    return builder.as_markup()



def repository_action_keyboard(full_name: str):
    builder = InlineKeyboardBuilder()
    repository_id = store_repository(full_name)
    search_token = get_repository_search(repository_id)

    builder.button(
        text="📥 Download Source Code",
        callback_data=_validate_callback_data(
            f"choice:src:{repository_id}"
        ),
    )
    builder.button(
        text="🚀 Browse Releases",
        callback_data=_validate_callback_data(
            f"choice:rel:{repository_id}"
        ),
    )
    builder.button(
        text="📄 View README",
        callback_data=_validate_callback_data(
            f"choice:readme:{repository_id}"
        ),
    )
    builder.button(
        text="⭐ Add to Favorites",
        callback_data=_validate_callback_data(
            f"favorite:add:{repository_id}"
        ),
    )

    if search_token:
        builder.button(
            text="⬅️ Back to Search Results",
            callback_data=_validate_callback_data(
                f"back:search:{search_token}"
            ),
        )

    builder.adjust(1)
    return builder.as_markup()




def releases_keyboard(full_name: str, releases: list):
    builder = InlineKeyboardBuilder()
    repository_id = store_repository(full_name)

    for release in releases[:MAX_RELEASES]:
        tag = release.get("tag_name")

        if not tag:
            continue

        name = release.get("name") or tag
        release_id = store_release(full_name, tag)

        builder.button(
            text=f"🚀 {name}"[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"rel:{release_id}"
            ),
        )

    builder.button(
        text="⬅️ Back to Repository",
        callback_data=_validate_callback_data(
            f"back:repo:{repository_id}"
        ),
    )

    builder.adjust(1)
    return builder.as_markup()



def download_keyboard(selections):
    builder = InlineKeyboardBuilder()

    for selection_id, label in selections:
        builder.button(
            text=label[:MAX_BUTTON_TEXT_LENGTH],
            callback_data=_validate_callback_data(
                f"get:{selection_id}"
            ),
        )

    builder.adjust(1)
    return builder.as_markup()



def readme_download_keyboard(token: str, repository_id: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="📥 Download README (.md)",
        callback_data=_validate_callback_data(
            f"readme_fmt:md:{token}:0"
        ),
    )

    builder.button(
        text="⬅️ Back to Repository",
        callback_data=_validate_callback_data(
            f"back:repo:{repository_id}"
        ),
    )

    builder.adjust(1)
    return builder.as_markup()
