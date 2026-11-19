from pathlib import Path

import aiosqlite

from radiotelephony.config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    edition TEXT,
    publication_year INTEGER,
    language TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent_id INTEGER,

    UNIQUE(source_id, code),

    FOREIGN KEY(source_id)
        REFERENCES sources(source_id) ON DELETE CASCADE,

    FOREIGN KEY(parent_id)
        REFERENCES topics(topic_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS questions (
    question_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    topic_id INTEGER,

    question_type TEXT NOT NULL,
    category TEXT NOT NULL,
    difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 3),

    question_text TEXT NOT NULL,
    options_json TEXT NOT NULL,
    answer_index INTEGER NOT NULL CHECK(answer_index BETWEEN 0 AND 3),

    short_explanation TEXT,
    explanation TEXT,

    reference_chapter INTEGER,
    reference_section TEXT,
    reference_section_title TEXT,
    reference_paragraph TEXT,
    page_printed TEXT,
    page_pdf INTEGER,
    reference_json TEXT NOT NULL,
    anchor TEXT,

    tags_json TEXT NOT NULL,
    source_payload_json TEXT NOT NULL,

    is_active INTEGER NOT NULL DEFAULT 1
        CHECK(is_active IN (0, 1)),

    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(source_id, external_id),

    FOREIGN KEY(source_id)
        REFERENCES sources(source_id) ON DELETE CASCADE,

    FOREIGN KEY(topic_id)
        REFERENCES topics(topic_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    language_code TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telegram_polls (
    poll_id TEXT PRIMARY KEY,
    question_pk INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT,

    FOREIGN KEY(question_pk)
        REFERENCES questions(question_pk)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id TEXT NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    selected_option_index INTEGER NOT NULL,
    is_correct INTEGER NOT NULL CHECK(is_correct IN (0, 1)),
    answered_at TEXT NOT NULL,

    UNIQUE(poll_id, telegram_user_id),

    FOREIGN KEY(poll_id)
        REFERENCES telegram_polls(poll_id),

    FOREIGN KEY(telegram_user_id)
        REFERENCES users(telegram_id)
);

CREATE INDEX IF NOT EXISTS idx_questions_source_topic
ON questions(source_id, topic_id, is_active);

CREATE INDEX IF NOT EXISTS idx_questions_category
ON questions(category, difficulty, is_active);

CREATE INDEX IF NOT EXISTS idx_attempts_user
ON quiz_attempts(telegram_user_id, answered_at);
"""


async def initialize_database(
    db_path: Path = DATABASE_PATH,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.executescript(SCHEMA)
        await db.commit()
