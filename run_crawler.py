#!/usr/bin/env python3
"""
Quant Finance Email Crawler
Automatically scrape quantitative finance papers, extract author emails.
"""
import os
import sys
import argparse
import shutil
from pathlib import Path

# Add src to path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# Import AFTER path setup
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env")

from src.utils.config import cfg
from src.crawler import QuantFinanceEmailCrawler


def main():
    parser = argparse.ArgumentParser(description="Quant Finance Email Crawler")
    parser.add_argument(
        "--max-papers", type=int, default=100,
        help="Max papers per source (default: 100)"
    )
    parser.add_argument(
        "--skip-pdf", action="store_true",
        help="Skip downloading PDFs (faster, email extraction only from metadata)"
    )
    parser.add_argument(
        "--force-cleanup", action="store_true",
        help="Clean up all downloaded papers before starting"
    )
    parser.add_argument(
        "--check-disk", action="store_true",
        help="Show disk usage and exit"
    )
    parser.add_argument(
        "--send-test", action="store_true",
        help="Send a test email to SMTP_USER"
    )
    args = parser.parse_args()

    if args.check_disk:
        from src.storage.paper_storage import PaperStorage
        storage = PaperStorage(cfg.PAPER_DOWNLOAD_DIR, cfg.MAX_PAPER_SIZE_MB)
        print(f"Disk usage: {storage.disk_usage()}")
        return

    if args.force_cleanup:
        papers_dir = Path(cfg.PAPER_DOWNLOAD_DIR)
        if papers_dir.exists():
            count = len(list(papers_dir.glob("*.pdf")))
            shutil.rmtree(papers_dir)
            papers_dir.mkdir(parents=True, exist_ok=True)
            print(f"Cleaned up {count} papers.")
        return

    if args.send_test:
        from src.emailer.sender import EmailSender
        from src.utils import RateLimiter
        rl = RateLimiter()
        sender = EmailSender(cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USER, cfg.SMTP_PASSWORD, rl)
        success = sender.send_email(
            cfg.SMTP_USER,
            "Test from Quant Finance Crawler",
            "This is a test email from the Quant Finance Email Crawler system.",
        )
        print(f"Test email {'sent' if success else 'failed'}")
        return

    # Run the crawler
    crawler = QuantFinanceEmailCrawler(cfg)

    print("=" * 60)
    print("  Quant Finance Email Crawler")
    print("  ===============================")
    print(f"  arXiv categories : {', '.join(cfg.ARXIV_CATEGORIES)}")
    print(f"  Max papers/source : {args.max_papers}")
    print(f"  PDF download      : {'Yes' if not args.skip_pdf else 'No (metadata only)'}")
    print(f"  Auto-cleanup PDFs : {cfg.DELETE_PAPERS_AFTER_EXTRACT}")
    print(f"  Output            : {cfg.AUTHOR_DATA_FILE}")
    print("=" * 60)

    results = crawler.run_full_pipeline(
        max_papers_per_source=args.max_papers,
        extract_from_pdfs=not args.skip_pdf,
    )

    print("\nDone! Results:")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
