"""Main crawler orchestrator - parallel batch processing."""
import time
import random
import concurrent.futures
from pathlib import Path
from typing import Optional

from src.scrapers.arxiv_scraper import ArxivScraper
from src.scrapers.ssrn_scraper import SSRNScraper
from src.scrapers.repec_scraper import RePEcScraper
from src.scrapers.crossref_scraper import CrossrefScraper
from src.scrapers.semanticscholar_scraper import SemanticScholarScraper
from src.scrapers.base import PaperInfo
from src.extractors.email_extractor import EmailExtractor, AuthorDB
from src.extractors.scholarly_client import ScholarlyClient
from src.extractors.orcid_client import OrcidEmailFinder
from src.storage.paper_storage import PaperStorage
from src.utils import (
    setup_logger, load_json, save_json, append_line,
    read_lines, RateLimiter
)
from src.utils.config import Config


def _process_single_paper(args, extractor, storage, cfg, logger, processed_ids):
    """Process a single paper - used for parallel execution."""
    paper, is_new = args
    if not is_new:
        return {"emails": [], "paper_id": paper.paper_id, "skipped": True}

    try:
        emails = extractor.extract_from_paper(paper)
        logger.info(f"[Worker] {paper.title[:60]} -> {len(emails)} email(s)")

        filepath = None
        if not emails and paper.pdf_url:
            filepath = storage.download_paper(paper)
            if filepath:
                text = storage.extract_text_from_pdf(filepath)
                if text:
                    extra = EmailExtractor._find_emails(text)
                    for e in extra:
                        if e not in emails:
                            emails.append(e)
                if cfg.DELETE_PAPERS_AFTER_EXTRACT:
                    storage.cleanup_paper(filepath)

        return {
            "paper_id": paper.paper_id,
            "emails": emails,
            "title": paper.title,
            "authors": paper.authors,
            "source": paper.source,
            "skipped": False,
        }
    except Exception as e:
        logger.error(f"[Worker] Error processing {paper.paper_id}: {e}")
        return {"emails": [], "paper_id": paper.paper_id, "skipped": False}


class QuantFinanceEmailCrawler:

    def __init__(self, config: Config):
        self.cfg = config
        self.logger = setup_logger(
            "quant_crawler", config.LOG_FILE, config.LOG_LEVEL
        )
        self.rate_limiter = RateLimiter(requests_per_minute=config.MAX_REQUESTS_PER_MINUTE)
        self.orcid = OrcidEmailFinder(rate_limiter=self.rate_limiter)
        self.scholarly = ScholarlyClient(rate_limiter=self.rate_limiter)
        self.extractor = EmailExtractor(
            rate_limiter=self.rate_limiter,
            scholarly_client=self.scholarly,
            orcid_client=self.orcid,
        )
        self.author_db = AuthorDB(config.AUTHOR_DATA_FILE)
        self.storage = PaperStorage(
            download_dir=config.PAPER_DOWNLOAD_DIR,
            max_size_mb=config.MAX_PAPER_SIZE_MB,
            auto_cleanup=config.DELETE_PAPERS_AFTER_EXTRACT,
            logger=self.logger,
        )
        self.processed_ids: set[str] = read_lines(config.PROCESSED_IDS_FILE)

        self.scrapers = [
            ArxivScraper(
                categories=config.ARXIV_CATEGORIES,
                rate_limiter=self.rate_limiter,
                logger=self.logger,
            ),
            CrossrefScraper(
                rate_limiter=self.rate_limiter,
                logger=self.logger,
            ),
            # SemanticScholarScraper requires API key for reliable access
            # SSRNScraper(rate_limiter=self.rate_limiter, logger=self.logger),
            # RePEcScraper(rate_limiter=self.rate_limiter, logger=self.logger),
        ]

    def run_full_pipeline(
        self,
        max_papers_per_source: int = 30,
        extract_from_pdfs: bool = True,
    ) -> dict:
        self.logger.info("=" * 60)
        self.logger.info("Starting Quant Finance Email Crawler Pipeline")
        self.logger.info("=" * 60)

        results = {
            "papers_scraped": 0,
            "papers_with_emails": 0,
            "new_authors": 0,
            "emails_found": 0,
            "papers_cleaned_up": 0,
            "papers_skipped": 0,
        }

        all_papers: list[PaperInfo] = []

        # Step 1: Scrape
        for scraper in self.scrapers:
            source = scraper.__class__.__name__
            self.logger.info(f"--- Scraping: {source} ---")
            try:
                papers = scraper.fetch_papers(max_results=max_papers_per_source)
                for p in papers:
                    is_new = p.paper_id not in self.processed_ids
                    all_papers.append((p, is_new))
                    if is_new:
                        results["papers_scraped"] += 1
            except Exception as e:
                self.logger.error(f"Scraper {source} failed: {e}")

        self.logger.info(f"Total papers to process: {len(all_papers)} "
                         f"(new: {sum(1 for _, n in all_papers if n)}, "
                         f"skipped: {sum(1 for _, n in all_papers if not n)})")

        # Step 2: Parallel email extraction (thread pool)
        paper_tasks = [
            (paper, is_new)
            for paper, is_new in all_papers
            if is_new
        ]

        if paper_tasks:
            # Process in parallel batches of 4
            batch_size = 4
            all_results = []
            for i in range(0, len(paper_tasks), batch_size):
                batch = paper_tasks[i:i + batch_size]
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    futures = {
                        executor.submit(
                            _process_single_paper,
                            args, self.extractor, self.storage,
                            self.cfg, self.logger, self.processed_ids
                        ): args for args in batch
                    }
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        all_results.append(result)

                        # Record authors - only first author gets the email (avoids shared inbox noise)
                        if result.get("emails") and not result.get("skipped"):
                            results["papers_with_emails"] += 1
                            first_author = result.get("authors", [None])[0]
                            if first_author:
                                before = self.author_db.count()
                                self.author_db.add_author(
                                    name=first_author,
                                    email=result["emails"][0],
                                    source=result.get("source", ""),
                                    paper_id=result.get("paper_id", ""),
                                )
                                if self.author_db.count() > before:
                                    results["new_authors"] += 1
                            results["emails_found"] += len(result["emails"])

                        # Mark processed
                        pid = result.get("paper_id", "")
                        if pid and pid not in self.processed_ids:
                            self.processed_ids.add(pid)
                            append_line(self.cfg.PROCESSED_IDS_FILE, pid)

                        time.sleep(random.uniform(0.3, 1.0))

        # Also add skipped papers if they have emails cached
        results["papers_skipped"] = sum(1 for _, n in all_papers if not n)

        self._report(results)
        return results

    def _report(self, results: dict) -> None:
        self.logger.info("=" * 60)
        self.logger.info("PIPELINE RESULTS")
        self.logger.info("=" * 60)
        for k, v in results.items():
            self.logger.info(f"  {k}: {v}")
        authors_with_email = self.author_db.get_authors_with_emails()
        self.logger.info(f"  Total authors with emails: {len(authors_with_email)}")
        storage_info = self.storage.disk_usage()
        self.logger.info(f"  Storage: {storage_info}")
        self.logger.info("=" * 60)
        save_json(authors_with_email, self.cfg.AUTHOR_DATA_FILE)
        self.logger.info(f"Author data saved to: {self.cfg.AUTHOR_DATA_FILE}")
