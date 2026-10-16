
import logging
import re
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
import time
from collections import defaultdict, deque
from services.callback_cache import (
    store_search_results,
    get_search_results,
)
from services.callback_cache import store_search_results

from keyboards.inline import repository_keyboard
from services.github import (
    GitHubService,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)


logger = logging.getLogger(__name__)

router = Router(name="search")

SEARCH_LIMIT = 5
SEARCH_WINDOW_SECONDS = 60

_user_searches: dict[int, deque[float]] = defaultdict(deque)


def is_search_allowed(user_id: int) -> bool:
    now = time.monotonic()
    timestamps = _user_searches[user_id]

    while timestamps and now - timestamps[0] >= SEARCH_WINDOW_SECONDS:
        timestamps.popleft()

    if len(timestamps) >= SEARCH_LIMIT:
        return False

    timestamps.append(now)
    return True


GITHUB_URL_PATTERN = re.compile(
    r"https?://github\.com/[^\s<>]+|"
    r"(?:www\.)?github\.com/[^\s<>]+",
    re.IGNORECASE,
)


def extract_github_repository(text: str) -> tuple[str, str] | None:
    """Extract and validate a GitHub repository URL."""

    match = GITHUB_URL_PATTERN.search(text)

    if not match:
        return None

    raw_url = match.group(0).rstrip(".,;!?)\"']}")

    if not raw_url.lower().startswith(("http://", "https://")):
        raw_url = f"https://{raw_url}"

    try:
        parsed = urlparse(raw_url)

        if parsed.scheme != "https":
            return None

        if parsed.hostname not in {"github.com", "www.github.com"}:
            return None

        if parsed.port not in (None, 443):
            return None

        if parsed.username is not None or parsed.password is not None:
            return None

    except ValueError:
        return None

    parts = parsed.path.strip("/").split("/")

    if len(parts) != 2:
        return None

    owner, repo = parts

    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        return None

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", owner):
        return None

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return None

    if repo in {".", ".."} or repo.endswith("."):
        return None

    return owner, repo


MAX_QUERY_LENGTH = 200
async def perform_repository_search(
    message: Message,
    query: str,
) -> None:
    query = query.strip()

    if not query:
        await message.answer(
            "Please enter a repository name or search query."
        )
        return

    if len(query) > MAX_QUERY_LENGTH:
        await message.answer(
            f"Your search query is too long. "
            f"Maximum length: {MAX_QUERY_LENGTH} characters."
        )
        return

    user = message.from_user

    if user is None or not is_search_allowed(user.id):
        await message.answer(
            "You have reached the search limit. "
            "Please wait a minute before searching again."
        )
        return

    status_message = await message.answer(
        "Searching GitHub repositories..."
    )

    try:
        async with GitHubService() as github:
            repository_info = extract_github_repository(query)


            if repository_info:
                owner, repo_name = repository_info
                repository = await github.get_repository(owner, repo_name)

                from keyboards.inline import repository_action_keyboard

                await status_message.edit_text(
                    f"📦 <b>{repository['full_name']}</b>\n\n"
                    "Choose what you want to download:",
                    reply_markup=repository_action_keyboard(
                        repository["full_name"]
                    ),
                    parse_mode="HTML",
                )
                return

            repositories = await github.search_repositories(
                query,
                per_page=10,
            )


        if not repositories:
            await status_message.edit_text(
                "No repositories were found."
            )
            return

        search_token = store_search_results(repositories)

        await status_message.edit_text(
            "📚 Select a repository from the list below:",
            reply_markup=repository_keyboard(repositories, search_token),
        )


    except GitHubNotFoundError:
        await status_message.edit_text(
            "❌ The requested GitHub repository was not found."
        )

    except GitHubRateLimitError:
        await status_message.edit_text(
            "⏳ GitHub rate limit reached. Please try again later."
        )

    except GitHubError:
        logger.exception("GitHub repository lookup failed")
        await status_message.edit_text(
            "❌ Failed to retrieve data from GitHub."
        )

    except Exception:
        logger.exception("Unexpected repository lookup error")
        await status_message.edit_text(
            "❌ An unexpected error occurred. Please try again later."
        )


@router.message(Command("repo"))
async def search_command(
    message: Message,
    state: FSMContext,
):
    query = (
        message.text.partition(" ")[2].strip()
        if message.text
        else ""
    )

    if not query:
        await state.set_state("waiting_for_repository_query")
        await message.answer(
            "Enter a repository name, search query, or GitHub URL."
        )
        return

    await state.clear()
    await perform_repository_search(message, query)


@router.message(
    StateFilter("waiting_for_repository_query"),
    F.text.regexp(
        r"(?i)(?:https?://)?(?:www\.)?github\.com/"
    ),
)
async def github_link_during_search(
    message: Message,
    state: FSMContext,
):
    await state.clear()
    await perform_repository_search(message, message.text or "")


@router.message(
    F.text.regexp(
        r"(?i)(?:https?://)?(?:www\.)?github\.com/"
    )
)
async def automatic_github_link_handler(message: Message):
    await perform_repository_search(message, message.text or "")


@router.message(
    StateFilter("waiting_for_repository_query"),
    F.text,
)
async def search_from_button(
    message: Message,
    state: FSMContext,
):
    query = (message.text or "").strip()

    if not query:
        await message.answer(
            "Please enter a repository name or search query."
        )
        return

    await state.clear()
    await perform_repository_search(message, query)

@router.callback_query(F.data == "back:search")
async def back_to_search(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    await state.set_state("waiting_for_repository_query")

    if callback.message:
        await callback.message.answer(
            "Enter a repository name, search query, or GitHub URL."
        )



@router.callback_query(F.data.startswith("back:search:"))
async def back_to_search_results(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    search_token = callback.data.removeprefix("back:search:")
    repositories = get_search_results(search_token)

    if repositories is None:
        await callback.answer(
            "These search results have expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()
    await callback.message.edit_text(
        "📚 Select a repository from the list below:",
        reply_markup=repository_keyboard(repositories, search_token),
    )
