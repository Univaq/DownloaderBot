
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(
    name: str,
    default: int,
    minimum: int = 1,
) -> int:
    value = os.getenv(name, str(default)).strip()

    try:
        number = int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a valid integer."
        ) from exc

    if number < minimum:
        raise RuntimeError(
            f"{name} must be at least {minimum}."
        )

    return number


@dataclass(frozen=True)
class Settings:
    bot_token: str
    github_token: str | None
    use_local_bot_api: bool
    local_bot_api_url: str
    database_path: Path
    downloads_dir: Path
    max_concurrent_jobs: int
    max_queue_size: int
    max_download_bytes: int

    @classmethod
    def load(cls) -> "Settings":
        bot_token = os.getenv("BOT_TOKEN", "").strip()

        if not bot_token:
            raise RuntimeError(
                "BOT_TOKEN is not configured. Check your .env file."
            )

        local_bot_api_url = os.getenv(
            "LOCAL_BOT_API_URL",
            "http://127.0.0.1:8081",
        ).strip().rstrip("/")

        if not local_bot_api_url:
            raise RuntimeError(
                "LOCAL_BOT_API_URL cannot be empty."
            )

        max_download_mb = env_int(
            "MAX_DOWNLOAD_MB",
            default=49,
        )

        return cls(
            bot_token=bot_token,
            github_token=os.getenv(
                "GITHUB_TOKEN",
                "",
            ).strip() or None,
            use_local_bot_api=env_bool(
                "USE_LOCAL_BOT_API",
                False,
            ),
            local_bot_api_url=local_bot_api_url,
            database_path=BASE_DIR / "data" / "jobs.db",
            downloads_dir=BASE_DIR / "downloads",
            max_concurrent_jobs=env_int(
                "MAX_CONCURRENT_JOBS",
                default=1,
            ),
            max_queue_size=env_int(
                "MAX_QUEUE_SIZE",
                default=100,
            ),
            max_download_bytes=max_download_mb * 1024 * 1024,
        )


settings = Settings.load()

settings.database_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)
settings.downloads_dir.mkdir(
    parents=True,
    exist_ok=True,
)
