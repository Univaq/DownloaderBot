
import secrets

import aiosqlite

from config import settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    repo_url TEXT NOT NULL,
    job_type TEXT NOT NULL DEFAULT 'source',
    file_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error TEXT,
    queue_message_id INTEGER,
    queue_chat_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created
ON jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created
ON jobs(user_id, created_at);

CREATE TABLE IF NOT EXISTS selections (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    download_url TEXT NOT NULL,
    file_name TEXT NOT NULL,
    job_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    repo_full_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, repo_full_name)
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_history_user_created
ON search_history(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_favorites_user_created
ON favorites(user_id, created_at);
"""


async def initialize_database() -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(SCHEMA)

        cursor = await db.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in await cursor.fetchall()}

        migrations = {
            "job_type": (
                "ALTER TABLE jobs ADD COLUMN "
                "job_type TEXT NOT NULL DEFAULT 'source'"
            ),
            "file_name": (
                "ALTER TABLE jobs ADD COLUMN file_name TEXT"
            ),
            "updated_at": (
                "ALTER TABLE jobs ADD COLUMN "
                "updated_at TEXT NOT NULL DEFAULT ''"
            ),
            "error": (
                "ALTER TABLE jobs ADD COLUMN error TEXT"
            ),
            "queue_message_id": (
                "ALTER TABLE jobs ADD COLUMN queue_message_id INTEGER"
            ),
            "queue_chat_id": (
                "ALTER TABLE jobs ADD COLUMN queue_chat_id INTEGER"
            ),
        }

        for column, sql in migrations.items():
            if column not in columns:
                await db.execute(sql)

        await db.execute(
            """
            UPDATE jobs
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at = ''
            """
        )

        await db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                updated_at = CURRENT_TIMESTAMP,
                error = 'Interrupted by process restart'
            WHERE status = 'running'
            """
        )

        await db.commit()


async def create_selection(
    user_id: int,
    chat_id: int,
    download_url: str,
    file_name: str,
    job_type: str,
) -> str:
    async with aiosqlite.connect(settings.database_path) as db:
        while True:
            selection_id = secrets.token_urlsafe(8)

            cursor = await db.execute(
                "SELECT 1 FROM selections WHERE id = ?",
                (selection_id,),
            )
            if await cursor.fetchone() is None:
                break

        await db.execute(
            """
            INSERT INTO selections (
                id,
                user_id,
                chat_id,
                download_url,
                file_name,
                job_type
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                selection_id,
                user_id,
                chat_id,
                download_url,
                file_name[:200],
                job_type,
            ),
        )

        await db.commit()

    return selection_id


async def get_selection(selection_id: str) -> dict | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT * FROM selections WHERE id = ?",
            (selection_id,),
        )
        row = await cursor.fetchone()

        return dict(row) if row else None


async def enqueue_selection(
    selection_id: str,
    user_id: int,
    queue_message_id: int | None = None,
    queue_chat_id: int | None = None,
) -> int | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT *
            FROM selections
            WHERE id = ? AND user_id = ?
            """,
            (selection_id, user_id),
        )
        selection = await cursor.fetchone()

        if selection is None:
            await db.rollback()
            return None

        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE status = 'queued'
            """
        )
        queued_count = (await cursor.fetchone())[0]

        if queued_count >= settings.max_queue_size:
            await db.rollback()
            return -1

        cursor = await db.execute(
            """
            INSERT INTO jobs (
                user_id,
                chat_id,
                repo_url,
                job_type,
                file_name,
                queue_message_id,
                queue_chat_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selection["user_id"],
                selection["chat_id"],
                selection["download_url"],
                selection["job_type"],
                selection["file_name"],
                queue_message_id,
                queue_chat_id,
            ),
        )

        job_id = cursor.lastrowid

        await db.execute(
            "DELETE FROM selections WHERE id = ?",
            (selection_id,),
        )

        await db.commit()
        return job_id


async def claim_next_job() -> dict | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT *
            FROM jobs
            WHERE status = 'queued'
            ORDER BY id
            LIMIT 1
            """
        )
        row = await cursor.fetchone()

        if row is None:
            await db.commit()
            return None

        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'running',
                updated_at = CURRENT_TIMESTAMP,
                error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (row["id"],),
        )

        if cursor.rowcount != 1:
            await db.rollback()
            return None

        job = dict(row)
        job["status"] = "running"

        await db.commit()
        return job


async def finish_job(job_id: int) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'completed',
                updated_at = CURRENT_TIMESTAMP,
                error = NULL
            WHERE id = ? AND status = 'running'
            """,
            (job_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def fail_job(job_id: int, error: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                updated_at = CURRENT_TIMESTAMP,
                error = ?
            WHERE id = ? AND status = 'running'
            """,
            (error[:500], job_id),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_queue_size() -> int:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE status = 'queued'
            """
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


MAX_FAVORITES_PER_USER = 20


async def add_favorite(user_id: int, repo_full_name: str) -> str:
    repo_full_name = repo_full_name.strip()

    if not repo_full_name or repo_full_name.count("/") != 1:
        return "invalid"

    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("BEGIN IMMEDIATE")

        cursor = await db.execute(
            """
            SELECT 1
            FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )

        if await cursor.fetchone():
            await db.commit()
            return "exists"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM favorites WHERE user_id = ?",
            (user_id,),
        )
        count = (await cursor.fetchone())[0]

        if count >= MAX_FAVORITES_PER_USER:
            await db.commit()
            return "full"

        await db.execute(
            """
            INSERT INTO favorites (user_id, repo_full_name)
            VALUES (?, ?)
            """,
            (user_id, repo_full_name),
        )
        await db.commit()
        return "added"


async def is_favorite(user_id: int, repo_full_name: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT 1
            FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )
        return await cursor.fetchone() is not None


async def remove_favorite(user_id: int, repo_full_name: str) -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            DELETE FROM favorites
            WHERE user_id = ? AND repo_full_name = ?
            """,
            (user_id, repo_full_name),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_favorites(user_id: int) -> list[str]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT repo_full_name
            FROM favorites
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]



async def add_search_history(user_id: int, query: str) -> None:
    query = query.strip()[:200]

    if not query:
        return

    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("BEGIN IMMEDIATE")

        await db.execute(
            """
            INSERT INTO search_history (user_id, query)
            VALUES (?, ?)
            """,
            (user_id, query),
        )

        # فقط ۲۰ جست‌وجوی جدیدتر هر کاربر نگه داشته می‌شود.
        await db.execute(
            """
            DELETE FROM search_history
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id
                  FROM search_history
                  WHERE user_id = ?
                  ORDER BY id DESC
                  LIMIT 20
              )
            """,
            (user_id, user_id),
        )

        await db.commit()



async def get_search_history(
    user_id: int,
    limit: int = 20,
) -> list[dict]:
    async with aiosqlite.connect(settings.database_path) as db:
        cursor = await db.execute(
            """
            SELECT id, query, created_at
            FROM search_history
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cursor.fetchall()

    return [
        {
            "id": row[0],
            "query": row[1],
            "created_at": row[2],
        }
        for row in rows
    ]
