"""Configuration loader."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Project root is one level above src/ (i.e., the directory containing run_crawler.py)
if "__file__" in globals():
    BASE_DIR = Path(__file__).parent.parent.parent.resolve()
else:
    BASE_DIR = Path(sys.argv[0] if sys.argv else ".").parent.resolve()

load_dotenv(BASE_DIR / ".env")

class Config:
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

    ARXIV_CATEGORIES = [
        c.strip() for c in os.getenv(
            "ARXIV_CATEGORIES",
            "econ.GN,q-fin.GN,q-fin.CP,q-fin.ST,q-fin.PM,q-fin.TR"
        ).split(",")
    ]

    MAX_EMAILS_PER_HOUR = int(os.getenv("MAX_EMAILS_PER_HOUR", "50"))
    MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "30"))

    DELETE_PAPERS_AFTER_EXTRACT = os.getenv("DELETE_PAPERS_AFTER_EXTRACT", "true").lower() == "true"
    MAX_PAPER_SIZE_MB = int(os.getenv("MAX_PAPER_SIZE_MB", "50"))

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = BASE_DIR / os.getenv("LOG_FILE", "data/logs/crawler.log")

    PAPER_DOWNLOAD_DIR = BASE_DIR / os.getenv("PAPER_DOWNLOAD_DIR", "data/papers")
    AUTHOR_DATA_FILE = BASE_DIR / os.getenv("AUTHOR_DATA_FILE", "data/authors/authors.json")
    PROCESSED_IDS_FILE = BASE_DIR / os.getenv("PROCESSED_IDS_FILE", "data/authors/processed.txt")
    EMAIL_QUEUE_FILE = BASE_DIR / os.getenv("EMAIL_QUEUE_FILE", "data/authors/email_queue.json")

    @classmethod
    def ensure_dirs(cls):
        for d in [cls.PAPER_DOWNLOAD_DIR, cls.LOG_FILE.parent, cls.AUTHOR_DATA_FILE.parent]:
            Path(d).mkdir(parents=True, exist_ok=True)

cfg = Config()
cfg.ensure_dirs()
