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
ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE)


def update_env(values: dict[str, str]) -> None:
    """Write settings into .env, keeping comments and unrelated lines, and apply them to this process.

    Values are single-line; ones with spaces or "#" are single-quoted, which python-dotenv reads literally.
    """
    clean = {}
    for key, value in values.items():
        value = " ".join(str(value or "").split())
        if "'" in value:
            raise ValueError(f"Giá trị của {key} không được chứa dấu nháy đơn.")
        clean[key] = value

    def line_for(key: str) -> str:
        return f"{key}='{clean[key]}'" if re.search(r"[\s#]", clean[key]) else f"{key}={clean[key]}"

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    remaining = set(clean)
    output = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            output.append(line_for(key))
            remaining.discard(key)
        else:
            output.append(line)
    output += [line_for(key) for key in clean if key in remaining]
    temporary = ENV_FILE.with_name(".env.tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)
    os.environ.update(clean)


def output_directory() -> Path:
    configured = os.environ.get("KV_OUTPUT_DIR", "").strip()
    directory = Path(configured).expanduser() if configured else ROOT / "output"
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def list_runs() -> list[tuple[Path, dict]]:
    """Saved video runs, newest first (folder names start with the creation time)."""
    runs = []
    for directory in sorted(output_directory().iterdir(), reverse=True):
        state_file = directory / "state.json"
        if not directory.is_dir() or not state_file.is_file():
            continue
        try:
            runs.append((directory, json.loads(state_file.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return runs


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
