"""Offline tests for the native-quiz database layer (no Telegram token)."""

import asyncio
import json
import sqlite3

from radiotelephony.database import initialize_database
from radiotelephony.quiz_storage import (
    book_by_selector,
    list_books,
    list_topics,
    random_question,
    record_answer,
    register_poll,
    register_user,
    user_stats,
)


def prepare_database(path):
    asyncio.run(initialize_database(path))
    with sqlite3.connect(path) as db:
        db.execute(
            """INSERT INTO sources
            (source_id, title, created_at, updated_at)
            VALUES ('example-book', 'Example Book', 'now', 'now')"""
        )
        db.execute(
            """INSERT INTO topics
            (source_id, code, title, kind)
            VALUES ('example-book', 'chapter:1', 'Communications', 'chapter')"""
        )
        chapter_id = db.execute("SELECT topic_id FROM topics").fetchone()[0]
        db.execute(
            """INSERT INTO topics
            (source_id, code, title, kind, parent_id)
            VALUES ('example-book', 'section:1.1', 'Basic Phrases', 'section', ?)""",
            (chapter_id,),
        )
        section_id = db.execute(
            "SELECT topic_id FROM topics WHERE code='section:1.1'"
        ).fetchone()[0]
        db.execute(
            """INSERT INTO questions (
                source_id, external_id, topic_id, question_type, category,
                difficulty, question_text, options_json, answer_index,
                reference_chapter, reference_section, page_printed,
                reference_json, tags_json, source_payload_json,
                content_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "example-book", "EX-001", section_id, "knowledge_check", "radio",
                1, "Choose the correct answer.",
                json.dumps(["One", "Two", "Three", "Four"]), 2,
                1, "1.1", "1-1", "{}", "[]", "{}", "hash", "now", "now",
            ),
        )
        db.commit()


def test_dynamic_book_topic_and_question(tmp_path):
    path = tmp_path / "questions.sqlite3"
    prepare_database(path)

    books = asyncio.run(list_books(path))
    assert len(books) == 1
    assert books[0]["count"] == 1
    selector = books[0]["selector"]

    book = asyncio.run(book_by_selector(selector, path))
    assert book["title"] == "Example Book"

    topics = asyncio.run(list_topics(selector, path))
    assert len(topics) == 1
    assert topics[0]["count"] == 1

    for scope in ("r", f"s:{selector}", f"t:{topics[0]['topic_id']}", "d:1"):
        question = asyncio.run(random_question(scope, path))
        assert question["external_id"] == "EX-001"

    assert asyncio.run(random_question("d:3", path)) is None


def test_answer_recorded_once_for_private_user(tmp_path):
    path = tmp_path / "questions.sqlite3"
    prepare_database(path)

    question = asyncio.run(random_question("r", path))
    asyncio.run(register_user(1234, "student", "Student", "en", path))
    asyncio.run(register_poll("poll-1", question["question_pk"], 1234, 5, path))

    assert asyncio.run(record_answer("poll-1", 9999, 2, path)) is None
    result = asyncio.run(record_answer("poll-1", 1234, 2, path))
    assert result is not None and result["correct"] is True
    assert result["correct_option"] == "Three"

    assert asyncio.run(record_answer("poll-1", 1234, 0, path)) is None
    assert asyncio.run(user_stats(1234, path)) == {"total": 1, "correct": 1}
