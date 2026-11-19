import argparse
import asyncio
import glob
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from radiotelephony.config import DATA_REPO_PATH, DATABASE_PATH
from radiotelephony.database import initialize_database
from radiotelephony.models import Question


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_catalog(source_filter=None):
    manifest_dir = DATA_REPO_PATH / "data" / "sources"
    manifests = sorted(manifest_dir.glob("*/manifest.json"))

    if not manifests:
        raise ValueError(f"No source manifests found in {manifest_dir}")

    bundles = []

    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        source_id = manifest["source_id"]

        if source_filter and source_id != source_filter:
            continue

        pattern = manifest_path.parent / manifest["question_glob"]
        files = sorted(glob.glob(str(pattern)))

        if not files:
            raise ValueError(f"No question files found for {source_id}")

        questions = []
        seen_ids = set()

        for filename in files:
            path = Path(filename)
            data = json.loads(path.read_text(encoding="utf-8"))

            if not isinstance(data, list):
                raise ValueError(f"Invalid JSON root: {path}")

            for index, raw in enumerate(data):
                question = Question.model_validate(raw)

                if question.id in seen_ids:
                    raise ValueError(f"Duplicate ID in {source_id}: {question.id}")

                seen_ids.add(question.id)
                questions.append((question, raw))

        bundles.append((manifest, questions))

    if source_filter and not bundles:
        raise ValueError(f"Unknown source: {source_filter}")

    return bundles


async def upsert_topic(
    db,
    source_id,
    code,
    title,
    kind,
    parent_id=None,
):
    await db.execute(
        """
        INSERT INTO topics (source_id, code, title, kind, parent_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id, code)
        DO UPDATE SET
            title = excluded.title,
            kind = excluded.kind,
            parent_id = excluded.parent_id
        """,
        (source_id, code, title, kind, parent_id),
    )

    cursor = await db.execute(
        "SELECT topic_id FROM topics WHERE source_id = ? AND code = ?",
        (source_id, code),
    )
    row = await cursor.fetchone()
    return row["topic_id"]


async def get_question_topic(db, source_id, question):
    ref = question.reference
    parent_id = None

    if ref and ref.chapter is not None:
        chapter_code = f"chapter:{ref.chapter}"
        chapter_title = ref.chapter_title or f"Chapter {ref.chapter}"

        parent_id = await upsert_topic(
            db,
            source_id,
            chapter_code,
            chapter_title,
            "chapter",
        )

    if ref and ref.section:
        return await upsert_topic(
            db,
            source_id,
            f"section:{ref.section}",
            ref.section_title or f"Section {ref.section}",
            "section",
            parent_id,
        )

    if parent_id is not None:
        return parent_id

    topic_tag = next(
        (tag.split(":", 1)[1] for tag in question.tags if tag.startswith("topic:")),
        None,
    )

    code = f"topic:{topic_tag or question.category}"
    title = topic_tag or question.category

    return await upsert_topic(db, source_id, code, title, "topic")


async def save_catalog(bundles):
    await initialize_database(DATABASE_PATH)

    inserted = 0
    updated = 0
    unchanged = 0

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("BEGIN")

        try:
            for manifest, questions in bundles:
                timestamp = now()
                source_id = manifest["source_id"]

                await db.execute(
                    """
                    INSERT INTO sources (
                        source_id, title, edition,
                        publication_year, language,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id)
                    DO UPDATE SET
                        title = excluded.title,
                        edition = excluded.edition,
                        publication_year = excluded.publication_year,
                        language = excluded.language,
                        updated_at = excluded.updated_at
                    """,
                    (
                        source_id,
                        manifest["title"],
                        manifest.get("edition"),
                        manifest.get("publication_year"),
                        manifest.get("language", "en"),
                        timestamp,
                        timestamp,
                    ),
                )

                for question, raw in questions:
                    topic_id = await get_question_topic(db, source_id, question)

                    payload = json.dumps(raw, ensure_ascii=False, sort_keys=True)
                    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

                    cursor = await db.execute(
                        """
                        SELECT content_hash FROM questions
                        WHERE source_id = ? AND external_id = ?
                        """,
                        (source_id, question.id),
                    )
                    existing = await cursor.fetchone()

                    if existing and existing["content_hash"] == content_hash:
                        unchanged += 1
                        continue

                    ref = question.reference

                    values = (
                        source_id,
                        question.id,
                        topic_id,
                        question.question_type,
                        question.category,
                        question.level,
                        question.question,
                        json.dumps(question.options, ensure_ascii=False),
                        question.answer_index,
                        question.short_explanation,
                        question.explanation,
                        ref.chapter if ref else None,
                        ref.section if ref else None,
                        ref.section_title if ref else None,
                        ref.paragraph if ref else None,
                        str(ref.page_printed)
                        if ref and ref.page_printed is not None
                        else None,
                        ref.page_pdf if ref else None,
                        json.dumps(
                            ref.model_dump(mode="json") if ref else {},
                            ensure_ascii=False,
                        ),
                        question.anchor,
                        json.dumps(question.tags, ensure_ascii=False),
                        payload,
                        int(question.is_active),
                        content_hash,
                        timestamp,
                        timestamp,
                    )

                    await db.execute(
                        """
                        INSERT INTO questions (
                            source_id, external_id, topic_id,
                            question_type, category, difficulty,
                            question_text, options_json, answer_index,
                            short_explanation, explanation,
                            reference_chapter, reference_section,
                            reference_section_title, reference_paragraph,
                            page_printed, page_pdf, reference_json,
                            anchor, tags_json, source_payload_json,
                            is_active, content_hash, created_at, updated_at
                        )
                        VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        ON CONFLICT(source_id, external_id)
                        DO UPDATE SET
                            topic_id = excluded.topic_id,
                            question_type = excluded.question_type,
                            category = excluded.category,
                            difficulty = excluded.difficulty,
                            question_text = excluded.question_text,
                            options_json = excluded.options_json,
                            answer_index = excluded.answer_index,
                            short_explanation = excluded.short_explanation,
                            explanation = excluded.explanation,
                            reference_chapter = excluded.reference_chapter,
                            reference_section = excluded.reference_section,
                            reference_section_title = excluded.reference_section_title,
                            reference_paragraph = excluded.reference_paragraph,
                            page_printed = excluded.page_printed,
                            page_pdf = excluded.page_pdf,
                            reference_json = excluded.reference_json,
                            anchor = excluded.anchor,
                            tags_json = excluded.tags_json,
                            source_payload_json = excluded.source_payload_json,
                            is_active = excluded.is_active,
                            content_hash = excluded.content_hash,
                            updated_at = excluded.updated_at
                        """,
                        values,
                    )

                    if existing:
                        updated += 1
                    else:
                        inserted += 1

            await db.commit()

        except Exception:
            await db.rollback()
            raise

    print(f"Database: {DATABASE_PATH}")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Unchanged: {unchanged}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source")
    args = parser.parse_args()

    try:
        bundles = load_catalog(args.source)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    total = sum(len(questions) for _, questions in bundles)

    print(f"Data repository: {DATA_REPO_PATH}")
    print(f"Sources: {len(bundles)}")
    print(f"Questions validated: {total}")

    for manifest, questions in bundles:
        print(f"  {manifest['source_id']}: {len(questions)} questions")

    if not args.apply:
        print("\nDRY RUN: No database changes made.")
        print("Run with --apply to import questions.")
        return 0

    try:
        asyncio.run(save_catalog(bundles))
    except Exception as exc:
        print(f"ERROR: Import failed: {exc}")
        return 1

    print("OK: Question bank imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
