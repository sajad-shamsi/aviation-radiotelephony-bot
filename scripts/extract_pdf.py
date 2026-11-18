import argparse
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "data/raw/icao-doc-9432.pdf"
OUTPUT_PATH = ROOT / "data/processed/icao-doc-9432-extracted.md"

PAGE_PATTERN = re.compile(r"(?<!\d)(\d{1,2}-\d{1,2})(?!\d)")


def detect_printed_page(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "unknown"

    header = lines[0]
    match = re.match(r"^(\d{1,2}-\d{1,2})(?:\s|$)", header)
    if not match:
        match = re.search(r"\s(\d{1,2}-\d{1,2})$", header)
    if match:
        return match.group(1)

    footer = lines[-1]
    return footer if PAGE_PATTERN.fullmatch(footer) else "unknown"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing extraction.",
    )
    args = parser.parse_args()

    if not PDF_PATH.is_file():
        raise SystemExit(f"ERROR: PDF not found: {PDF_PATH}")

    if OUTPUT_PATH.exists() and not args.overwrite:
        raise SystemExit(
            "ERROR: Output already exists. Use --overwrite to regenerate."
        )

    page_blocks = []
    pages_with_text = 0
    pages_without_text = []
    printed_labels = 0

    with pymupdf.open(str(PDF_PATH)) as document:
        total_pages = len(document)

        for pdf_page, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).strip()
            printed_page = detect_printed_page(text)

            if text:
                pages_with_text += 1
            else:
                pages_without_text.append(pdf_page)

            if printed_page != "unknown":
                printed_labels += 1

            marker = (
                f"<!-- PDF_PAGE: {pdf_page} | "
                f"PRINTED_PAGE: {printed_page} -->"
            )

            page_blocks.append(f"{marker}\n\n{text}")

    if pages_with_text == 0:
        raise SystemExit("ERROR: No extractable text found. OCR may be required.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_PATH.write_text(
        "\n\n---\n\n".join(page_blocks) + "\n",
        encoding="utf-8",
    )

    print(f"PDF pages: {total_pages}")
    print(f"Pages with text: {pages_with_text}")
    print(f"Pages without text: {len(pages_without_text)}")
    print(f"Printed page labels detected: {printed_labels}")
    print(f"Output size: {OUTPUT_PATH.stat().st_size:,} bytes")

    if pages_without_text:
        print(f"WARNING: Pages without text: {pages_without_text}")

    if printed_labels == 0:
        print("WARNING: No printed page labels detected.")

    print("OK: PDF extraction completed")


if __name__ == "__main__":
    main()
