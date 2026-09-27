import json
import logging
import os
import re
import unicodedata
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def output_directory() -> Path:
    configured = os.environ.get("KV_OUTPUT_DIR", "").strip()
    directory = Path(configured).expanduser() if configured else ROOT / "output"
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def http_user_agent() -> str:
    return os.environ.get("KV_HTTP_USER_AGENT", "").strip() or "KnowledgeVideo/0.1 (local prototype)"


def setup_logging() -> None:
    log_dir = output_directory() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("kv")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(handler)


def slug(value: str, fallback: str = "video", limit: int = 60) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).replace("đ", "d").replace("Đ", "D")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:limit].rstrip("-") or fallback


class RunStore:
    """One folder per video run; every step result is persisted in state.json."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.assets = directory / "assets"
        self.music = directory / "music"
        self.render = directory / "render"
        for child in (self.assets, self.music):
            child.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls, topic: str) -> "RunStore":
        name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}__{slug(topic)}"
        return cls(output_directory() / name)

    def save(self, state: dict) -> None:
        temporary = self.directory / "state.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.directory / "state.json")
