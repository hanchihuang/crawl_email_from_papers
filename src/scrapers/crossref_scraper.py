"""Crossref API scraper - excellent for finding academic paper author emails."""
import re
import time
import urllib.parse
from typing import Optional
from src.scrapers.base import BaseScraper, PaperInfo
from src.utils import download_with_retry


class CrossrefScraper(BaseScraper):

    BASE_URL = "https://api.crossref.org"

    FINANCE_KEYWORDS = [
        "quantitative", "portfolio", "trading", "factor", "option", "risk",
        "stock", "bond", "derivative", "investment", "volatility", "market",
        "asset pricing", "returns", "high frequency", "algorithmic",
        "machine learning", "deep learning", "reinforcement",
        "crypto", "blockchain", "fintech", "esg", "sustainable",
    ]

    def __init__(self, rate_limiter=None, **kwargs):
        super().__init__(**kwargs)
        self.rate_limiter = rate_limiter
        self._processed_ids: set[str] = set()
        self._email_cache: dict[str, list[str]] = {}

    def fetch_papers(
        self, max_results: int = 100,
        query: str = "quantitative finance",
        filter_type: str = "journal-article",
        **kwargs
    ) -> list[PaperInfo]:
        papers: list[PaperInfo] = []

        # Try multiple finance-related search queries
        queries = [
            "quantitative finance trading",
            "portfolio optimization machine learning",
            "financial machine learning",
            "asset pricing factor models",
            "option pricing derivatives",
            "risk management algorithmic trading",
        ]

        for q in queries:
            if len(papers) >= max_results:
                break
            self.log("INFO", f"Crossref search: {q}")
            batch = self._search_crossref(q, max_results - len(papers))
            for p in batch:
                if p.paper_id not in self._processed_ids:
                    papers.append(p)
                    self._processed_ids.add(p.paper_id)
            time.sleep(self._random_sleep())

        self.log("INFO", f"Fetched {len(papers)} papers from Crossref")
        return papers

    def _search_crossref(self, query: str, limit: int) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        url = (
            f"{self.BASE_URL}/works?"
            f"query={urllib.parse.quote(query)}"
            f"&rows={limit}"
            f"&mailto=research@example.com"
        )
        text = download_with_retry(url, timeout=30)
        if not text:
            return []
        try:
            import json
            data = json.loads(text.decode("utf-8"))
            items = data.get("message", {}).get("items", [])
            for item in items:
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
        except Exception as e:
            self.log("WARNING", f"Crossref parse error: {e}")
        return papers

    def _parse_item(self, item: dict) -> Optional[PaperInfo]:
        try:
            paper_id = str(item.get("DOI", ""))
            if not paper_id:
                return None

            title_list = item.get("title", [])
            title = title_list[0] if title_list else "N/A"

            abstract = item.get("abstract", "") or ""
            abstract = re.sub(r"<[^>]+>", " ", abstract).strip()

            authors = []
            for author in item.get("author", []):
                name = " ".join(filter(None, [
                    author.get("given", ""),
                    author.get("family", "")
                ]))
                if name:
                    authors.append(name)

            published = None
            date_parts = item.get("published-print") or item.get("published-online") or {}
            date_list = date_parts.get("date-parts", [])
            if date_list:
                d = date_list[0]
                published = "-".join(str(x).zfill(2) for x in d[:3])

            publisher = item.get("publisher", "")
            URL = item.get("URL", f"https://doi.org/{paper_id}")

            # Try to get author emails from the 'author' field (some APIs include this)
            emails = []
            for author in item.get("author", []):
                email = author.get("email")
                if email and "@" in email:
                    emails.append(email)

            return PaperInfo(
                paper_id=paper_id,
                title=title,
                abstract=abstract,
                authors=authors,
                source="crossref",
                url=URL,
                pdf_url=None,
                published_date=published,
                categories=["finance"],
            )
        except Exception:
            return None

    @staticmethod
    def _random_sleep() -> float:
        import random
        return random.uniform(1.5, 3.0)
