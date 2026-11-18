import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/processed/icao-doc-9432-extracted.md"
TOC = ROOT / "data/processed/toc.json"
TARGET = ROOT / "data/processed/sections_toc"

PAGE_RE = re.compile(
    r"^<!-- PDF_PAGE: (\d+) \| PRINTED_PAGE: ([\w-]+) -->$"
)
SECTION_RE = re.compile(
    r"^\s*(\d{1,2}\.\d{1,2})(?!\.\d)\s+(.+?)\s*$"
)
CHAPTER_RE = re.compile(r"^\s*Chapter\s+\d+\s*$", re.IGNORECASE)
PAGE_FOOTER = re.compile(r"^\d{1,2}-\d{1,2}$")
RUNNING_HEADER = re.compile(
    r"^(?:\d{1,2}-\d{1,2}\s+Manual of Radiotelephony|"
    r"Chapter\s+\d+\.\s+.*\d{1,2}-\d{1,2})$"
)


def save_active(active, results):
    if active is None:
        return

    item = active["item"]
    lines = active["lines"]

    if not any(
        line.strip() and not line.startswith("<!-- PDF_PAGE:")
        for line in lines
    ):
        raise SystemExit(f"ERROR: Empty section: {item['id']}")

    results[item["id"]] = {
        "lines": lines,
        "start_pdf": active["start_pdf"],
        "start_printed": active["start_printed"],
    }


def main():
    if not SOURCE.is_file() or not TOC.is_file():
        raise SystemExit("ERROR: Extraction or TOC file missing")

    toc = json.loads(TOC.read_text(encoding="utf-8"))
    sections = toc["sections"]
    by_id = {item["id"]: item for item in sections}
    toc_pages = set(toc["toc_pdf_pages"])

    if len(sections) != 68 or len(by_id) != 68:
        raise SystemExit("ERROR: Expected 68 unique TOC sections")

    if TARGET.exists():
        raise SystemExit(
            f"ERROR: Output already exists: {TARGET}"
        )

    active = None
    results = {}
    seen = set()

    current_pdf = None
    current_printed = None
    current_marker = None
    marker_pending = False

    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        marker = PAGE_RE.fullmatch(line.strip())

        if marker:
            current_pdf = int(marker[1])
            current_printed = marker[2]
            current_marker = line
            marker_pending = True
            continue

        if current_pdf in toc_pages or line.strip() == "---":
            continue

        if CHAPTER_RE.fullmatch(line.strip()):
            save_active(active, results)
            active = None
            marker_pending = False
            continue

        if (
            PAGE_FOOTER.fullmatch(line.strip())
            or RUNNING_HEADER.fullmatch(line.strip())
        ):
            continue

        heading = SECTION_RE.match(line)

        if heading and heading.group(1) in by_id:
            section_id = heading.group(1)
            item = by_id[section_id]

            if section_id in seen:
                raise SystemExit(f"ERROR: Duplicate heading: {section_id}")

            if current_pdf is None or current_printed == "unknown":
                raise SystemExit(
                    f"ERROR: Missing actual page reference for {section_id}"
                )

            if (
                current_pdf != item["page_pdf"]
                or current_printed != item["page_printed"]
            ):
                print(
                    f"WARNING: TOC/body page discrepancy for {section_id}: "
                    f"TOC {item['page_printed']} (PDF {item['page_pdf']}), "
                    f"actual {current_printed} (PDF {current_pdf})"
                )

            save_active(active, results)

            active = {
                "item": item,
                "lines": [current_marker],
                "start_pdf": current_pdf,
                "start_printed": current_printed,
            }
            seen.add(section_id)
            marker_pending = False
            continue

        if active is not None:
            if marker_pending and current_marker:
                active["lines"].append(current_marker)
                marker_pending = False

            active["lines"].append(line)

    save_active(active, results)

    missing = sorted(set(by_id) - seen)

    if missing:
        raise SystemExit(f"ERROR: Missing sections: {missing}")

    if len(results) != 68:
        raise SystemExit(f"ERROR: Expected 68 outputs, got {len(results)}")

    TARGET.mkdir(parents=True)

    for item in sections:
        section_id = item["id"]

        header = [
            f"# Chapter {item['chapter']} — {item['chapter_title']}",
            f"## Section {section_id} — {item['title']}",
            "",
            (
                f"**TOC-listed page:** Printed {item['page_printed']} "
                f"| PDF {item['page_pdf']}"
            ),
            (
                f"**Actual section start:** Printed "
                f"{results[section_id]['start_printed']} "
                f"| PDF {results[section_id]['start_pdf']}"
            ),
            "",
            f"<!-- SECTION_ID: {section_id} -->",
            "",
        ]

        body = "\n".join(results[section_id]["lines"]).strip()
        output = "\n".join(header) + body + "\n"

        (TARGET / f"{section_id}.md").write_text(
            output,
            encoding="utf-8",
        )

    print(f"Chapters: {len(toc['chapters'])}")
    print(f"Sections created: {len(results)}")

    for section_id in ("5.1", "5.2", "5.3", "5.4"):
        item = by_id[section_id]
        print(
            f"{section_id}: printed {item['page_printed']} "
            f"-> PDF {item['page_pdf']}"
        )

    print(f"Output: {TARGET}")
    print("OK: TOC-driven section splitting completed")


if __name__ == "__main__":
    main()
