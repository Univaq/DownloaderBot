
import logging

import re
from urllib.parse import urlparse


from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
import html
from datetime import datetime
from keyboards.inline import (
    repository_action_keyboard,
    releases_keyboard,
    download_keyboard,
    readme_download_keyboard,
)
from services.callback_cache import (
    get_repository,
    get_release,
    store_readme,
    get_readme,
)
from services.github import (
    GitHubService,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
)
from repositories.jobs import create_selection, enqueue_selection
from services.callback_cache import store_repository

logger = logging.getLogger(__name__)
router = Router(name="releases")



def back_to_repository_keyboard(full_name: str):
    repository_id = store_repository(full_name)
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )

    builder.adjust(1)
    return builder.as_markup()


async def show_github_error(
    callback: CallbackQuery,
    error_message: str,
    full_name: str | None = None,
) -> None:
    if callback.message is not None:
        keyboard = (
            back_to_repository_keyboard(full_name)
            if full_name
            else None
        )

        await callback.message.edit_text(
            error_message,
            reply_markup=keyboard,
        )
    else:
        await callback.answer(error_message, show_alert=True)

def format_repository_date(value: str | None) -> str:
    if not value:
        return "Unknown"

    try:
        date = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return date.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return "Unknown"


def clean_readme_content(content: str) -> str:
    """Remove decorative elements and clean README Markdown."""
    content = re.sub(
        r"<!--.*?-->",
        "",
        content,
        flags=re.DOTALL,
    )

    # Remove HTML images and SVG elements.
    content = re.sub(
        r"<img\b[^>]*>",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"<svg\b[^>]*>.*?</svg\s*>",
        "",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Remove Markdown images.
    content = re.sub(
        r"!\[[^\]]*\]\([^)]*\)",
        "",
        content,
    )
    content = re.sub(
        r"!\[[^\]]*\]\[[^\]]*\]",
        "",
        content,
    )

    # Remove empty Markdown links.
    content = re.sub(
        r"\[\s*\]\([^)]*\)",
        "",
        content,
    )

    # Remove HTML tags while preserving their text.
    content = re.sub(
        r"<br\s*/?>",
        "\n",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"</(p|div|h[1-6]|li|tr|section)\s*>",
        "\n",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"<[^>]+>", "", content)

    # Remove reference definitions used for images or badges.
    content = re.sub(
        r"^\s*\[[^\]]+\]:\s*\S+.*$",
        "",
        content,
        flags=re.MULTILINE,
    )

    # Normalize whitespace.
    content = re.sub(r"[ \t]+\n", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()



def format_repository_card(
    full_name: str,
    repository: dict,
) -> str:
    name = html.escape(
        repository.get("full_name") or full_name
    )
    description = html.escape(
        repository.get("description") or "No description available."
    )
    language = html.escape(
        repository.get("language") or "Not specified"
    )
    branch = html.escape(
        repository.get("default_branch") or "Unknown"
    )
    url = html.escape(
        repository.get("html_url")
        or f"https://github.com/{full_name}",
        quote=True,
    )

    stars = repository.get(
        "stars",
        repository.get("stargazers_count", 0),
    ) or 0
    forks = repository.get(
        "forks",
        repository.get("forks_count", 0),
    ) or 0
    issues = repository.get(
        "open_issues",
        repository.get("open_issues_count", 0),
    ) or 0
    watchers = repository.get(
        "watchers",
        repository.get("subscribers_count", 0),
    ) or 0

    updated = format_repository_date(
        repository.get("updated_at")
    )

    license_info = repository.get("license")

    if isinstance(license_info, dict):
        license_name = (
            license_info.get("spdx_id")
            or license_info.get("name")
            or "Not specified"
        )
    elif isinstance(license_info, str):
        license_name = license_info
    else:
        license_name = "Not specified"

    license_name = html.escape(license_name)

    status = "Archived" if repository.get("archived") else "Active"

    if repository.get("fork"):
        status += " · Fork"

    return (
        f"📦 <b>{name}</b>\n\n"
        f"<i>{description}</i>\n\n"
        f"⭐ <b>Stars:</b> {stars:,}\n"
        f"🍴 <b>Forks:</b> {forks:,}\n"
        f"👀 <b>Watchers:</b> {watchers:,}\n"
        f"🐛 <b>Open issues:</b> {issues:,}\n\n"
        f"💻 <b>Language:</b> {language}\n"
        f"🌿 <b>Default branch:</b> <code>{branch}</code>\n"
        f"📜 <b>License:</b> {license_name}\n"
        f"🕒 <b>Last updated:</b> {updated}\n"
        f"📌 <b>Status:</b> {html.escape(status)}\n\n"
        f'<a href="{url}">View on GitHub ↗</a>\n\n'
        f"<b>What would you like to explore?</b>"
    )



TELEGRAM_MESSAGE_LIMIT = 3500



def format_markdown_inline(text: str) -> str:
    pattern = re.compile(
        r"!\[([^\]]*)\]\([^)]*\)"
        r"|\[([^\]]+)\]\(([^)\s]+)(?:\s+[\"'][^)]*[\"'])?\)"
        r"|`([^`\n]+)`"
        r"|\*\*(.+?)\*\*"
        r"|__(.+?)__"
        r"|(?<!\*)\*([^*\n]+)\*(?!\*)"
        r"|(?<!_)_([^_\n]+)_(?!_)"
    )

    parts = []
    position = 0

    for match in pattern.finditer(text):
        parts.append(html.escape(text[position:match.start()]))
        groups = match.groups()

        if groups[0] is not None:
            # Omit Markdown images.
            pass
        elif groups[1] is not None:
            label = groups[1]
            url = groups[2]

            if url.startswith(("https://", "http://")):
                safe_url = html.escape(url, quote=True)
                safe_label = html.escape(label)
                parts.append(f'<a href="{safe_url}">{safe_label}</a>')
            else:
                parts.append(html.escape(label))
        elif groups[3] is not None:
            parts.append(f"<code>{html.escape(groups[3])}</code>")
        elif groups[4] is not None:
            parts.append(f"<b>{html.escape(groups[4])}</b>")
        elif groups[5] is not None:
            parts.append(f"<b>{html.escape(groups[5])}</b>")
        elif groups[6] is not None:
            parts.append(f"<i>{html.escape(groups[6])}</i>")
        elif groups[7] is not None:
            parts.append(f"<i>{html.escape(groups[7])}</i>")

        position = match.end()

    parts.append(html.escape(text[position:]))
    return "".join(parts)



def split_readme_preview(content: str) -> list[str]:
    blocks = []
    paragraph = []
    code_lines = []
    in_code = False
    code_marker = None

    def flush_paragraph():
        if paragraph:
            text = " ".join(line.strip() for line in paragraph)
            if text:
                blocks.append(format_markdown_inline(text))
            paragraph.clear()

    def add_code_chunks(source_lines):
        current = []

        for line in source_lines:
            candidate = "\n".join(current + [line])

            if current and len(candidate) > TELEGRAM_MESSAGE_LIMIT - 20:
                blocks.append(
                    "<pre>"
                    + html.escape("\n".join(current))
                    + "</pre>"
                )
                current = [line]
            else:
                current.append(line)

        if current:
            blocks.append(
                "<pre>"
                + html.escape("\n".join(current))
                + "</pre>"
            )

    for line in content.splitlines():
        stripped = line.strip()

        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]

            if not in_code:
                flush_paragraph()
                in_code = True
                code_marker = marker
                code_lines = []
            elif marker == code_marker:
                add_code_chunks(code_lines)
                code_lines = []
                in_code = False
                code_marker = None

            continue

        if in_code:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            continue

        heading = re.match(
            r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$",
            line,
        )

        if heading:
            flush_paragraph()
            blocks.append(
                "<b>"
                + format_markdown_inline(heading.group(1))
                + "</b>"
            )
            continue

        if re.match(r"^\s*([-*_]\s*){3,}$", line):
            flush_paragraph()
            blocks.append("──────────")
            continue

        list_item = re.match(r"^\s*[-*+]\s+(.+)$", line)
        numbered_item = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        quote = re.match(r"^\s*>\s?(.*)$", line)

        if list_item:
            flush_paragraph()
            blocks.append("• " + format_markdown_inline(list_item.group(1)))
        elif numbered_item:
            flush_paragraph()
            blocks.append(format_markdown_inline(line.strip()))
        elif quote:
            flush_paragraph()
            blocks.append(
                "│ " + format_markdown_inline(quote.group(1))
            )
        else:
            paragraph.append(line)

    flush_paragraph()

    if in_code:
        add_code_chunks(code_lines)

    messages = []
    current = ""

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block

        if current and len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = candidate

    if current:
        messages.append(current)

    return messages or ["<i>This README is empty.</i>"]


def readme_preview_keyboard(
    readme_id: str,
    full_name: str,
):
    repository_id = store_repository(full_name)
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ Download README",
        callback_data=f"readme_fmt:md:{readme_id}:0",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )
    builder.adjust(1)

    return builder.as_markup()

@router.callback_query(F.data.startswith("repo:"))
async def select_repository(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    token = callback.data.removeprefix("repo:")
    full_name = get_repository(token)

    if full_name is None or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            repository = await github.get_repository(owner, repo)

        message_text = format_repository_card(
            full_name,
            repository,
        )

    except GitHubRateLimitError:
        message_text = (
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ GitHub rate limit reached. "
            "Repository details are temporarily unavailable.\n\n"
            "<b>Choose an action below</b>"
        )

    except GitHubError:
        logger.exception(
            "Failed to retrieve repository details: %s",
            full_name,
        )
        message_text = (
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ Repository details could not be loaded.\n\n"
            "<b>Choose an action below</b>"
        )

    except Exception:
        logger.exception(
            "Unexpected error loading repository details: %s",
            full_name,
        )
        message_text = (
            f"📁 <b>{html.escape(full_name)}</b>\n\n"
            "⚠️ An unexpected error occurred while loading details.\n\n"
            "<b>Choose an action below</b>"
        )

    await callback.message.edit_text(
        message_text,
        reply_markup=repository_action_keyboard(full_name),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("choice:src:"))
async def choose_source_code(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    token = callback.data.removeprefix("choice:src:")
    full_name = get_repository(token)

    if full_name is None:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()
    await send_source_selection(callback, full_name)


@router.callback_query(F.data.startswith("choice:rel:"))
async def choose_releases(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    token = callback.data.removeprefix("choice:rel:")
    full_name = get_repository(token)

    if full_name is None:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    if full_name.count("/") != 1:
        await callback.answer(
            "Invalid repository selection.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        if not releases:
            await callback.message.edit_text(
                f"🚀 <b>Releases</b>\n"
                f"<code>{full_name}</code>\n\n"
                "No releases have been published for this repository.",
                reply_markup=back_to_repository_keyboard(full_name),
                parse_mode="HTML",
            )
            return

        await callback.message.edit_text(
            f"🚀 <b>Available Releases</b>\n"
            f"<code>{full_name}</code>\n\n"
            "Select a release:",
            reply_markup=releases_keyboard(full_name, releases),
            parse_mode="HTML",
        )

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository not found.",
            full_name,
        )

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )

    except GitHubError:
        logger.exception("Failed to fetch repository releases")
        await show_github_error(
            callback,
            "❌ Failed to retrieve repository releases.",
            full_name,
        )

    except Exception:
        logger.exception("Unexpected error while fetching releases")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )



async def send_source_selection(
    callback: CallbackQuery,
    full_name: str,
    tag: str | None = None,
):
    if callback.message is None or full_name.count("/") != 1:
        return

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            repository = await github.get_repository(owner, repo)
            ref = tag or repository["default_branch"]
            source_url = github.get_source_url(owner, repo, ref)

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository or requested version not found.",
            full_name,
        )
        return

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
            full_name,
        )
        return

    except GitHubError:
        logger.exception("Failed to retrieve repository source")
        await show_github_error(
            callback,
            "❌ Failed to retrieve repository source code.",
            full_name,
        )
        return

    except Exception:
        logger.exception("Unexpected error while retrieving source")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
            full_name,
        )
        return

    selection_id = await create_selection(
        user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
        download_url=source_url,
        file_name=f"{repo}-{ref}.zip",
        job_type="source",
    )

    repository_id = store_repository(full_name)

    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬇️ Download Source Code",
        callback_data=f"get:{selection_id}",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )
    builder.adjust(1)

    await callback.message.edit_text(
        f"📦 <b>Source Code</b>\n"
        f"Repository: <code>{full_name}</code>\n"
        f"Version: <code>{ref}</code>\n\n"
        "Press the button below to add the download to the queue.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )




def source_selection_keyboard(selection_id: str, repository_id: str):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="⬇️ Download Source Code",
        callback_data=f"get:{selection_id}",
    )
    builder.button(
        text="⬅️ Back to Repository",
        callback_data=f"back:repo:{repository_id}",
    )

    builder.adjust(1)
    return builder.as_markup()



@router.callback_query(F.data.startswith("rel:"))
async def release_selected(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    token = callback.data.removeprefix("rel:")
    release_info = get_release(token)

    if release_info is None:
        await callback.answer(
            "This release selection has expired. Please search again.",
            show_alert=True,
        )
        return

    full_name, tag = release_info

    if full_name.count("/") != 1 or not tag:
        await callback.answer(
            "Invalid release selection.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

    except GitHubNotFoundError:
        await show_github_error(
            callback,
            "❌ Repository or release not found.",
        )
        return

    except GitHubRateLimitError:
        await show_github_error(
            callback,
            "⏳ GitHub rate limit reached. Please try again later.",
        )
        return

    except GitHubError:
        logger.exception("Failed to retrieve release assets")
        await show_github_error(
            callback,
            "❌ Failed to retrieve release information.",
        )
        return

    except Exception:
        logger.exception("Unexpected error while retrieving release")
        await show_github_error(
            callback,
            "❌ An unexpected error occurred. Please try again later.",
        )
        return

    release = next(
        (
            item
            for item in releases
            if item.get("tag_name") == tag
        ),
        None,
    )

    if release is None:
        await callback.message.edit_text(
            "❌ This release could not be found.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
        return

    selections = []

    for asset in release.get("assets", [])[:10]:
        selection_id = await create_selection(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            download_url=asset["download_url"],
            file_name=asset["name"],
            job_type="asset",
        )

        size_mb = asset.get("size", 0) / (1024 * 1024)

        selections.append(
            (
                selection_id,
                f"⬇️ {asset['name']} ({size_mb:.1f} MB)",
            )
        )

    if not selections:
        await callback.message.edit_text(
            f"🚀 <b>Release:</b> <code>{tag}</code>\n\n"
            "This release has no downloadable assets.",
            reply_markup=back_to_repository_keyboard(full_name),
            parse_mode="HTML",
        )
        return

    repository_id = store_repository(full_name)

    builder = InlineKeyboardBuilder()

    for selection_id, label in selections:
        builder.button(
            text=label[:60],
            callback_data=f"get:{selection_id}",
        )

    builder.button(
        text="⬅️ Back to Releases",
        callback_data=f"back:releases:{repository_id}",
    )

    builder.adjust(1)

    await callback.message.edit_text(
        f"🚀 <b>Release Assets</b>\n"
        f"Repository: <code>{full_name}</code>\n"
        f"Version: <code>{tag}</code>\n\n"
        "Select a file to download:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("get:"))
async def enqueue_download(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    selection_id = callback.data.removeprefix("get:")

    queue_message = await callback.message.answer(
        "⏳ Download request added to the queue."
    )

    try:
        job_id = await enqueue_selection(
            selection_id=selection_id,
            user_id=callback.from_user.id,
            queue_message_id=queue_message.message_id,
            queue_chat_id=queue_message.chat.id,
        )

    except Exception:
        try:
            await queue_message.delete()
        except Exception:
            logger.debug(
                "Failed to delete queue message after enqueue error",
                exc_info=True,
            )

        logger.exception("Failed to enqueue download")
        await callback.answer(
            "Failed to add the download to the queue.",
            show_alert=True,
        )
        return

    if job_id is None or job_id == -1:
        try:
            await queue_message.delete()
        except Exception:
            logger.debug(
                "Failed to delete rejected queue message",
                exc_info=True,
            )

        if job_id == -1:
            await callback.answer(
                "The download queue is currently full.",
                show_alert=True,
            )
        else:
            await callback.answer(
                "This selection is invalid or has already been used.",
                show_alert=True,
            )

        return

    await callback.answer("Download added to the queue.")





@router.callback_query(F.data.startswith("choice:readme:"))
async def choose_readme(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer(
            "Invalid request.",
            show_alert=True,
        )
        return

    token = callback.data.removeprefix("choice:readme:")
    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    message = callback.message

    try:
        owner, repo = full_name.split("/", 1)

        async with GitHubService() as github:
            files = await github.get_readme_files(owner, repo)

        if not files:
            await message.edit_text(
                "No README files found.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        if len(files) == 1:
            await show_readme_format_options(
                message,
                full_name,
                files[0],
            )
            return

        builder = InlineKeyboardBuilder()

        for index, file in enumerate(files[:20]):
            builder.button(
                text=f"📄 {file['name']}"[:60],
                callback_data=f"readme_lang:{token}:{index}",
            )

        builder.button(
            text="⬅️ Back to Repository",
            callback_data=f"back:repo:{token}",
        )

        builder.adjust(1)

        await message.edit_text(
            "Choose a README file:",
            reply_markup=builder.as_markup(),
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "Repository or README files were not found.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub rate limit reached. Please try again later.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except GitHubError:
        logger.exception("Failed to retrieve README files")
        await message.edit_text(
            "Failed to retrieve README files.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

    except Exception:
        logger.exception("Unexpected error while finding README files")
        await message.edit_text(
            "An unexpected error occurred.",
            reply_markup=back_to_repository_keyboard(full_name),
        )

async def show_readme_format_options(
    message,
    full_name: str,
    readme_file: dict,
):
    owner, repo = full_name.split("/", 1)
    path = readme_file["path"]

    readme_id = store_readme(
        full_name,
        path,
        readme_file.get("download_url"),
    )

    async with GitHubService() as github:
        content = await github.get_readme_content(
            owner,
            repo,
            path,
        )

    content = clean_readme_content(content)

    preview_limit = 500
    preview_content = content[:preview_limit]

    if len(content) > preview_limit:
        last_newline = preview_content.rfind("\n")
        last_space = preview_content.rfind(" ")

        cut_position = max(last_newline, last_space)

        if cut_position > 300:
            preview_content = preview_content[:cut_position]

        preview_content += (
            "\n\n... Preview shortened. "
            "Download the README to read the full file."
        )

    preview_html = split_readme_preview(preview_content)
    preview_text = "\n\n".join(preview_html)

    keyboard = readme_preview_keyboard(
        readme_id,
        full_name,
    )

    text = (
        f"📄 <b>README Preview</b> ( <code>{html.escape(readme_file['name'])}</code> )\n\n"
        f"{preview_text}"
    )

    await message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("readme_lang:"))
async def choose_readme_language(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("Invalid request.", show_alert=True)
        return

    try:
        _, token, index_text = callback.data.split(":", 2)
        index = int(index_text)
    except ValueError:
        await callback.answer("Invalid selection.", show_alert=True)
        return

    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer("Please search again.", show_alert=True)
        return

    await callback.answer()
    message = callback.message

    try:
        await message.edit_text("Loading README...")

        owner, repo = full_name.split("/", 1)

        async with GitHubService() as github:
            files = await github.get_readme_files(owner, repo)

        if index < 0 or index >= min(len(files), 20):
            await message.edit_text(
                "README selection is no longer available.",
                reply_markup=back_to_repository_keyboard(full_name),
            )
            return

        await show_readme_format_options(
            message,
            full_name,
            files[index],
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "Repository or README files were not found.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub rate limit reached. Please try again later.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubError:
        logger.exception("Failed to retrieve selected README")
        await message.edit_text(
            "Failed to retrieve README content.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except Exception:
        logger.exception("Unexpected error while selecting README")
        await message.edit_text(
            "An unexpected error occurred.",
            reply_markup=back_to_repository_keyboard(full_name),
        )


@router.callback_query(F.data.startswith("readme_fmt:"))
async def choose_readme_format(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer("Invalid request.", show_alert=True)
        return

    try:
        _, file_format, readme_id, index_text = callback.data.split(":", 3)
        index = int(index_text)
    except ValueError:
        await callback.answer("Invalid selection.", show_alert=True)
        return

    if file_format != "md" or index != 0:
        await callback.answer("Invalid selection.", show_alert=True)
        return

    info = get_readme(readme_id)

    if not info:
        await callback.answer("Please select the README again.", show_alert=True)
        return

    full_name, path, _ = info

    if full_name.count("/") != 1:
        await callback.answer("Invalid repository.", show_alert=True)
        return


    await callback.answer()

    message = callback.message

    try:
        owner, repo = full_name.split("/", 1)

        await message.edit_text("Downloading README...")

        async with GitHubService() as github:
            content = await github.get_readme_content(
                owner,
                repo,
                path,
            )

        filename = path.rsplit("/", 1)[-1] or "README.md"

        document = BufferedInputFile(
            content.encode("utf-8"),
            filename=filename,
        )

        await message.answer_document(
            document=document,
            caption=f"README for {full_name}",
        )

        builder = InlineKeyboardBuilder()
        repository_id = store_repository(full_name)

        builder.button(
            text="⬅️ Back to Repository",
            callback_data=f"back:repo:{repository_id}",
        )
        builder.adjust(1)

        await message.edit_text(
            "README downloaded successfully.",
            reply_markup=builder.as_markup(),
        )

    except GitHubNotFoundError:
        await message.edit_text(
            "Repository or README file was not found.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubRateLimitError:
        await message.edit_text(
            "GitHub rate limit reached. Please try again later.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except GitHubError:
        logger.exception("Failed to download README")
        await message.edit_text(
            "Failed to download README.",
            reply_markup=back_to_repository_keyboard(full_name),
        )
    except Exception:
        logger.exception("Unexpected error while downloading README")
        await message.edit_text(
            "An unexpected error occurred.",
            reply_markup=back_to_repository_keyboard(full_name),
        )



@router.callback_query(F.data.startswith("back:repo:"))
async def back_to_repository(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("back:repo:")
    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            repository = await github.get_repository(owner, repo)

        message_text = format_repository_card(full_name, repository)

    except GitHubError:
        logger.exception("Failed to load repository details: %s", full_name)
        message_text = (
            f"📦 <b>{html.escape(full_name)}</b>\n\n"
            "Repository details are temporarily unavailable.\n\n"
            "<b>Choose an action below</b>"
        )

    await callback.message.edit_text(
        message_text,
        reply_markup=repository_action_keyboard(full_name),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("back:releases:"))
async def back_to_releases(callback: CallbackQuery):
    if not callback.data or callback.message is None:
        await callback.answer("Invalid request.", show_alert=True)
        return

    token = callback.data.removeprefix("back:releases:")
    full_name = get_repository(token)

    if not full_name or full_name.count("/") != 1:
        await callback.answer(
            "This selection has expired. Please search again.",
            show_alert=True,
        )
        return

    await callback.answer()

    owner, repo = full_name.split("/", 1)

    try:
        async with GitHubService() as github:
            releases = await github.get_releases(owner, repo)

        if not releases:
            await callback.message.edit_text(
                f"No releases found for <code>{full_name}</code>.",
                parse_mode="HTML",
                reply_markup=repository_action_keyboard(full_name),
            )
            return

        await callback.message.edit_text(
            f"🚀 <b>Available Releases</b>\n"
            f"<code>{full_name}</code>\n\n"
            "Select a release:",
            reply_markup=releases_keyboard(full_name, releases),
            parse_mode="HTML",
        )

    except GitHubError:
        logger.exception("Failed to retrieve repository releases")
        await callback.message.edit_text(
            "Failed to retrieve repository releases.",
            reply_markup=repository_action_keyboard(full_name),
        )
