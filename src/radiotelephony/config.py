import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")


def resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DATA_REPO_PATH = resolve_path(
    os.getenv("DATA_REPO_PATH", "../aviation-radiotelephony-data")
)

DATABASE_PATH = resolve_path(os.getenv("DATABASE_PATH", "data/radiotelephony.sqlite3"))
