import asyncio
import sqlite3

from radiotelephony.database import initialize_database


def test_database_initialization(tmp_path):
    db_path = tmp_path / "test.sqlite3"

    asyncio.run(initialize_database(db_path))

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert {
        "sources",
        "topics",
        "questions",
        "users",
        "telegram_polls",
        "quiz_attempts",
    }.issubset(tables)
