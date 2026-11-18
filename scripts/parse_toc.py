import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/processed/icao-doc-9432-extracted.md"
OUTPUT = ROOT / "data/processed/toc.json"

TOC_PAGES = {7, 8, 9}

PAGE_MARKER = re.compile(
    r"^<!-- PDF_PAGE: (\d+) \| PRINTED_PAGE: ([\w-]+) -->$"
)
PAGE_SUFFIX = re.compile(r"(\d{1,2}-\d{1,2})\s*$")
CHAPTER_RE = re.compile(r"^CHAPTER\s+(\d+)\s*[—–-]\s*(.+)$", re.IGNORECASE)
SECTION_RE = re.compile(r"^(\d{1,2}\.\d{1,2})(?!\.\d)\s+(.+)$")


def main():
    if not SOURCE.is_file():
        raise SystemExit("ERROR: Extracted PDF text not found")

    text = SOURCE.read_text(encoding="utf-8")
    pages = {}
    page_map = {}
    current_page = None

    for line in text.splitlines():
        marker = PAGE_MARKER.fullmatch(line.strip())

        if marker:
            current_page = int(marker[1])
            pages[current_page] = []
            printed = marker[2]

            if printed != "unknown":
                if printed in page_map and page_map[printed] != current_page:
                    raise SystemExit(f"ERROR: Duplicate page mapping: {printed}")
                page_map[printed] = current_page

            continue

        if current_page in TOC_PAGES:
            pages[current_page].append(line)

    if not TOC_PAGES.issubset(pages):
        raise SystemExit("ERROR: Missing Table of Contents pages")

    chapters = []
    sections = []
    current_chapter = None
    pending = None

    def save_section(item, printed):
        chapter = int(item["id"].split(".")[0])
        if chapter != current_chapter["number"]:
            raise SystemExit(f"ERROR: Chapter mismatch: {item['id']}")

        sections.append({
            "id": item["id"],
            "chapter": chapter,
            "chapter_title": current_chapter["title"],
            "title": item["title"],
            "page_printed": printed,
            "page_pdf": page_map.get(printed),
        })

    for pdf_page in sorted(TOC_PAGES):
        for raw in pages[pdf_page]:
            line = raw.strip()
            if not line or line == "Page":
                continue

            suffix = PAGE_SUFFIX.search(line)
            printed = suffix.group(1) if suffix else None

            label = line[:suffix.start()].strip() if suffix else line
            label = re.sub(r"\.{2,}\s*$", "", label).strip()

            chapter_match = CHAPTER_RE.match(label)

            if chapter_match:
                if pending:
                    raise SystemExit("ERROR: Incomplete TOC section")

                number = int(chapter_match[1])
                title = chapter_match[2].strip()

                if not printed:
                    raise SystemExit(f"ERROR: Missing page for Chapter {number}")

                current_chapter = {
                    "number": number,
                    "title": title,
                    "page_printed": printed,
                    "page_pdf": page_map.get(printed),
                }
                chapters.append(current_chapter)
                continue

            section_match = SECTION_RE.match(label)

            if section_match:
                if pending:
                    raise SystemExit("ERROR: Incomplete TOC section")

                pending = {
                    "id": section_match[1],
                    "title": section_match[2].strip(),
                }

                if printed:
                    save_section(pending, printed)
                    pending = None

                continue

            if pending:
                pending["title"] += " " + label

                if printed:
                    save_section(pending, printed)
                    pending = None

    if pending:
        raise SystemExit("ERROR: Incomplete final TOC entry")

    ids = [section["id"] for section in sections]

    if len(chapters) != 11 or len(sections) != 68:
        raise SystemExit(
            f"ERROR: Expected 11 chapters and 68 sections; "
            f"found {len(chapters)} and {len(sections)}"
        )

    if len(set(ids)) != len(ids):
        raise SystemExit("ERROR: Duplicate section IDs")

    missing = [s["id"] for s in sections if s["page_pdf"] is None]
    if missing:
        raise SystemExit(f"ERROR: Missing PDF page mappings: {missing}")

    sample = next(s for s in sections if s["id"] == "5.1")

    if sample["page_printed"] != "5-1" or sample["page_pdf"] != 55:
        raise SystemExit(f"ERROR: Incorrect Section 5.1 mapping: {sample}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "source": "ICAO Doc 9432, 4th Edition, 2007",
                "toc_pdf_pages": sorted(TOC_PAGES),
                "chapters": chapters,
                "sections": sections,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Chapters: {len(chapters)}")
    print(f"Sections: {len(sections)}")
    print("Section 5.1: printed 5-1 -> PDF 55")
    print(f"Output: {OUTPUT}")
    print("OK: Table of Contents parsed and validated")


if __name__ == "__main__":
    main()
