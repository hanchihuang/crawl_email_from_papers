"""Semantic Scholar API scraper - often includes author emails."""
import re
import time
import urllib.parse
from typing import Optional
from src.scrapers.base import BaseScraper, PaperInfo
from src.utils import download_with_retry


class SemanticScholarScraper(BaseScraper):

    API_URL = "https://api.semanticscholar.org/graph/v1"
    FIELDS = (
        "title,abstract,authors,year,venue,journal,publicationVenue,"
        "externalIds,openAccessPdf,url,citationCount,influentialCitationCount"
    )

    FINANCE_KEYWORDS = [
        "quantitative", "portfolio", "trading", "factor", "option", "risk",
        "stock", "bond", "derivative", "investment", "volatility", "market",
        "asset pricing", "returns", "high frequency", "algorithmic",
        "machine learning", "deep learning", "reinforcement learning",
        "crypto", "blockchain", "fintech", "esg", "sustainable",
        "credit", "lending", "banking", "insurance", "fintech",
    ]

    def __init__(self, rate_limiter=None, **kwargs):
        super().__init__(**kwargs)
        self.rate_limiter = rate_limiter
        self._processed_ids: set[str] = set()

    def fetch_papers(
        self, max_results: int = 100, **kwargs
    ) -> list[PaperInfo]:
        papers: list[PaperInfo] = []

        queries = [
            "quantitative finance trading",
            "portfolio optimization machine learning",
            "financial machine learning",
        ]

        for q in queries:
            if len(papers) >= max_results:
                break
            self.log("INFO", f"Semantic Scholar search: {q}")
            # Fetch 50 per query instead of 100
            batch = self._search(q, min(50, max_results - len(papers)))
            for p in batch:
                if p.paper_id not in self._processed_ids:
                    papers.append(p)
                    self._processed_ids.add(p.paper_id)
            time.sleep(self._random_sleep())

        self.log("INFO", f"Fetched {len(papers)} papers from Semantic Scholar")
        return papers

    def _search(self, query: str, limit: int) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        url = (
            f"{self.API_URL}/paper/search?"
            f"query={urllib.parse.quote(query)}"
            f"&fields={self.FIELDS}"
            f"&limit={limit}"
            f"&venue=finance"
        )
        # Try twice with exponential backoff
        text = download_with_retry(url, timeout=60, max_retries=2)
        if not text:
            self.log("WARNING", f"Semantic Scholar 429 rate limit - skipping {query}")
            return []
        try:
            import json
            data = json.loads(text.decode("utf-8"))
            for item in data.get("data", []):
                paper = self._parse_item(item)
                if paper:
                    papers.append(paper)
        except Exception as e:
            self.log("WARNING", f"Semantic Scholar parse error: {e}")
        return papers

    def _parse_item(self, item: dict) -> Optional[PaperInfo]:
        try:
            paper_id = item.get("paperId", "")
            if not paper_id:
                return None

            title = item.get("title", "N/A")
            abstract = item.get("abstract", "") or ""
            year = item.get("year")
            venue = item.get("venue", "") or item.get("journal", "") or ""

            authors = [
                a.get("name", "")
                for a in item.get("authors", [])
                if a.get("name")
            ]

            external = item.get("externalIds", {}) or {}
            doi = external.get("DOI", "")

            openaccess = item.get("openAccessPdf", {}) or {}
            pdf_url = openaccess.get("url") if isinstance(openaccess, dict) else None

            return PaperInfo(
                paper_id=paper_id,
                title=title,
                abstract=abstract,
                authors=authors,
                source="semanticscholar",
                url=item.get("url", f"https://www.semanticscholar.org/paper/{paper_id}"),
                pdf_url=pdf_url,
                published_date=str(year) if year else None,
                categories=[venue],
            )
        except Exception:
            return None

    @staticmethod
    def _random_sleep() -> float:
        import random
        return random.uniform(1.0, 2.5)
