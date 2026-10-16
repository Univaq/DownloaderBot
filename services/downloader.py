
import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urljoin, urlparse

import logging

import aiofiles
import httpx

from config import settings


ALLOWED_HOSTS = {
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5
CHUNK_SIZE = 64 * 1024

MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2

ProgressCallback = Callable[
    [int, int | None],
    Awaitable[None],
]

logger = logging.getLogger(__name__)


def is_allowed_github_url(url: str) -> bool:
    """Validate a GitHub download URL."""

    try:
        parsed = urlparse(url)

        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.lower() in ALLOWED_HOSTS
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


async def download_to_temp_once(
    url: str,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Download a file to a temporary path with progress reporting."""

    if not is_allowed_github_url(url):
        raise ValueError("The download URL is not allowed.")

    max_size = settings.max_download_bytes

    if not isinstance(max_size, int) or max_size <= 0:
        raise ValueError("The configured download size limit is invalid.")

    settings.downloads_dir.mkdir(parents=True, exist_ok=True)

    fd, filename = tempfile.mkstemp(
        prefix="ghbot_",
        suffix=".tmp",
        dir=settings.downloads_dir,
    )
    path = Path(filename)

    try:
        os.close(fd)
        fd = -1

        timeout = httpx.Timeout(
            60.0,
            connect=15.0,
        )

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "GitHubFinderBot/1.0"},
        ) as client:
            current_url = url

            for redirect_count in range(MAX_REDIRECTS + 1):
                if not is_allowed_github_url(current_url):
                    raise ValueError(
                        "The download redirect destination is not allowed."
                    )

                async with client.stream(
                    "GET",
                    current_url,
                ) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("Location")

                        if not location:
                            raise ValueError(
                                "The download redirect has no destination."
                            )

                        if redirect_count >= MAX_REDIRECTS:
                            raise ValueError(
                                "Too many download redirects."
                            )

                        next_url = urljoin(
                            str(response.url),
                            location,
                        )

                        if not is_allowed_github_url(next_url):
                            raise ValueError(
                                "The download redirect destination is not allowed."
                            )

                        current_url = next_url
                        continue

                    response.raise_for_status()

                    if response.status_code != 200:
                        raise ValueError("The download server returned an unexpected status.")

                    content_type = response.headers.get("content-type", "")
                    if content_type.lower().startswith("text/html"):
                        raise ValueError("The download server returned an HTML page.")

                    content_length = response.headers.get("content-length")

                    if content_length is not None:
                        if not content_length.isdigit():
                            raise ValueError("The download server returned an invalid file size.")

                        total_size = int(content_length)

                        if total_size > max_size:
                            raise ValueError("The file exceeds the configured download limit.")
                    else:
                        total_size = None

                    downloaded = 0

                    async with aiofiles.open(path, "wb") as output:
                        async for chunk in response.aiter_bytes(
                            CHUNK_SIZE
                        ):
                            if not chunk:
                                continue

                            downloaded += len(chunk)

                            if downloaded > max_size:
                                raise ValueError(
                                    "The file exceeds the configured download limit."
                                )

                            await output.write(chunk)

                            if progress_callback is not None:
                                try:
                                    await progress_callback(downloaded, total_size)
                                except Exception:
                                    import logging

                                    logging.getLogger(__name__).debug(
                                        "Download progress callback failed",
                                        exc_info=True,
                                    )

                    return path

        raise ValueError("The download could not be completed.")

    except BaseException:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass

        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

        raise


async def download_to_temp(
    url: str,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """Download a file with retries for transient network errors."""

    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            return await download_to_temp_once(
                url,
                progress_callback=progress_callback,
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt >= MAX_DOWNLOAD_ATTEMPTS:
                raise

            logger.warning(
                "Temporary download network error; retrying attempt %s of %s.",
                attempt + 1,
                MAX_DOWNLOAD_ATTEMPTS,
            )

            await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)


async def delete_temp_file(path: Path) -> None:
    """Delete a temporary file belonging to this bot."""

    root = settings.downloads_dir.resolve()
    target = Path(os.path.abspath(path))

    if target.parent != root:
        raise ValueError("The temporary file path is invalid.")

    if (
        not target.name.startswith("ghbot_")
        or target.suffix != ".tmp"
    ):
        raise ValueError("The temporary file path is invalid.")

    if target.is_symlink():
        raise ValueError("Symbolic links cannot be deleted as temporary files.")

    await asyncio.to_thread(
        target.unlink,
        missing_ok=True,
    )
