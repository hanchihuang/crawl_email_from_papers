"""Shared utilities."""
import json
import logging
import time
import random
import hashlib
from pathlib import Path
from typing import Optional, Any
from datetime import datetime


def setup_logger(name: str, log_file, level: str = "INFO") -> logging.Logger:
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        sh = logging.StreamHandler()
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fmt)
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


class RateLimiter:
    """Simple rate limiter for HTTP requests and email sending."""

    def __init__(self, requests_per_minute: int = 30):
        self.rpm = requests_per_minute
        self.window: list[float] = []
        self._lock = False

    def wait(self) -> None:
        now = time.time()
        self.window = [t for t in self.window if now - t < 60]
        if len(self.window) >= self.rpm:
            sleep_time = 60 - (now - self.window[0]) + random.uniform(0.5, 2)
            time.sleep(max(0.1, sleep_time))
        self.window.append(time.time())
        time.sleep(random.uniform(0.3, 1.5))

    def email_wait(self, max_per_hour: int = 50) -> None:
        now = time.time()
        self.window = [t for t in self.window if now - t < 3600]
        if len(self.window) >= max_per_hour:
            sleep_time = 3600 - (now - self.window[0]) + random.uniform(5, 15)
            time.sleep(max(1, sleep_time))
        self.window.append(time.time())
        time.sleep(random.uniform(3, 8))


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(data: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def append_line(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(value + "\n")

def read_lines(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def safe_filename(paper_id: str) -> str:
    return paper_id.replace("/", "_").replace("\\", "_")

def download_with_retry(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    headers: Optional[dict] = None,
    stream: bool = False,
) -> Optional[bytes]:
    import requests
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; finance-email-crawler/1.0; "
            "+https://github.com/quant-crawler)"
        )
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=default_headers, timeout=timeout, stream=stream)
            if resp.status_code == 200:
                return resp.content
            elif resp.status_code == 429:
                wait = 2 ** attempt * 10 + random.uniform(5, 15)
                time.sleep(wait)
            else:
                return None
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt + random.uniform(1, 3))
    return None
