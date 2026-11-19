"""SQLite operations for the Telegram native-quiz interface.

The question importer owns catalog changes; the bot only reads questions and
writes user attempts. All selectors are database IDs, not hard-coded chapters.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from radiotelephony.config import DATABASE_PATH


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def list_books(db_path: Path = DATABASE_PATH) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.rowid AS selector, s.title,
                   (SELECT COUNT(*) FROM questions q
                    WHERE q.source_id = s.source_id AND q.is_active = 1) AS count
            FROM sources s
            WHERE EXISTS (SELECT 1 FROM questions q
                          WHERE q.source_id = s.source_id AND q.is_active = 1)
            ORDER BY s.title
            """
        )
        return [dict(row) for row in await cursor.fetchall()]


async def book_by_selector(selector: int, db_path: Path = DATABASE_PATH) -> dict | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT rowid AS selector, title FROM sources WHERE rowid = ?",
            (selector,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_topics(selector: int, db_path: Path = DATABASE_PATH) -> list[dict]:
    """Show chapter/topic roots, counting directly assigned and child questions."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT t.topic_id, t.code, t.title, t.kind,
                   (SELECT COUNT(*) FROM questions q
                    LEFT JOIN topics child ON child.topic_id = q.topic_id
                    WHERE q.source_id = t.source_id AND q.is_active = 1
                      AND (q.topic_id = t.topic_id OR child.parent_id = t.topic_id)
                   ) AS count
            FROM topics t
            JOIN sources s ON s.source_id = t.source_id
            WHERE s.rowid = ? AND t.kind IN ('chapter', 'topic')
            ORDER BY CASE WHEN t.kind = 'chapter' THEN 0 ELSE 1 END,
                     CAST(substr(t.code, instr(t.code, ':') + 1) AS INTEGER), t.title
            """,
            (selector,),
        )
        return [dict(row) for row in await cursor.fetchall() if row["count"] > 0]


async def random_question(
    scope: str = "r", db_path: Path = DATABASE_PATH
) -> dict | None:
    where = ["q.is_active = 1"]
    values = []

    if scope == "r":
        pass
    elif scope.startswith("s:") and scope[2:].isdigit():
        where.append("s.rowid = ?")
        values.append(int(scope[2:]))
    elif scope.startswith("t:") and scope[2:].isdigit():
        where.append(
            "(q.topic_id = ? OR EXISTS "
            "(SELECT 1 FROM topics child WHERE child.topic_id = q.topic_id "
            "AND child.parent_id = ?))"
        )
        values.extend((int(scope[2:]), int(scope[2:])))
    elif scope in {"d:1", "d:2", "d:3"}:
        where.append("q.difficulty = ?")
        values.append(int(scope[2:]))
    else:
        raise ValueError(f"Invalid question scope: {scope}")

    sql = f"""
        SELECT q.question_pk, q.external_id, q.question_text, q.options_json,
               q.answer_index, q.reference_chapter, q.reference_section,
               q.page_printed, q.difficulty, s.title AS source_title
        FROM questions q
        JOIN sources s ON s.source_id = q.source_id
        WHERE {' AND '.join(where)}
        ORDER BY RANDOM() LIMIT 1
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql, values)
        row = await cursor.fetchone()
        return dict(row) if row else None


async def register_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
    db_path: Path = DATABASE_PATH,
) -> None:
    now = timestamp()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO users (
                telegram_id, username, first_name, language_code,
                created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                language_code = excluded.language_code,
                last_seen_at = excluded.last_seen_at
            """,
            (user_id, username, first_name, language_code, now, now),
        )
        await db.commit()


async def register_poll(
    poll_id: str, question_pk: int, chat_id: int, message_id: int,
    db_path: Path = DATABASE_PATH,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            INSERT INTO telegram_polls (
                poll_id, question_pk, chat_id, message_id, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (poll_id, question_pk, chat_id, message_id, timestamp()),
        )
        await db.commit()


async def record_answer(
    poll_id: str,
    user_id: int,
    chosen: int,
    db_path: Path = DATABASE_PATH,
) -> dict | None:
    """Record the first answer only, and only for that user's private poll."""
    if chosen not in range(4):
        return None

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """
            SELECT p.chat_id, q.answer_index, q.external_id, q.options_json,
                   q.reference_chapter, q.reference_section, q.page_printed,
                   s.title AS source_title
            FROM telegram_polls p
            JOIN questions q ON q.question_pk = p.question_pk
            JOIN sources s ON s.source_id = q.source_id
            WHERE p.poll_id = ?
            """,
            (poll_id,),
        )
        row = await cursor.fetchone()
        if row is None or row["chat_id"] != user_id:
            return None

        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO quiz_attempts (
                poll_id, telegram_user_id, selected_option_index,
                is_correct, answered_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (poll_id, user_id, chosen, int(chosen == row["answer_index"]), timestamp()),
        )
        inserted = cursor.rowcount == 1
        await db.commit()
        if not inserted:
            return None

        result = dict(row)
        result["correct"] = chosen == row["answer_index"]
        result["correct_option"] = json.loads(row["options_json"])[row["answer_index"]]
        return result


async def user_stats(user_id: int, db_path: Path = DATABASE_PATH) -> dict:
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(is_correct), 0) AS correct
            FROM quiz_attempts WHERE telegram_user_id = ?
            """,
            (user_id,),
        )
        total, correct = await cursor.fetchone()
        return {"total": total, "correct": correct}
