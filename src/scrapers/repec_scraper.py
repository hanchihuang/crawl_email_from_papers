"""RePEc (Research Papers in Economics) scraper."""
import re
import time
from typing import Optional
from src.scrapers.base import BaseScraper, PaperInfo
from src.utils import download_with_retry


class RePEcScraper(BaseScraper):

    # RePEc has many series - finance related ones
    SERIES = [
        "_HANDL_collections:series_finance",
        "series/wpgaq:Finance",
        "series/nb:Finance",
        "series/bofit:Finance",
        "series/ec:Finance",
    ]

    def __init__(self, rate_limiter=None, **kwargs):
        super().__init__(**kwargs)
        self.rate_limiter = rate_limiter
        self._processed_ids: set[str] = set()

    def fetch_papers(self, max_results: int = 100, **kwargs) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        self.log("INFO", "Fetching RePEc papers")

        # Search RePEc for quantitative finance
        search_url = (
            "https://search.repec.org/RePEc.cgi?"
            "p=finance&q=quantitative&o=50&sf=date&so=sd&Cl=10&qm=any"
        )
        text = download_with_retry(search_url, timeout=30)
        if text:
            try:
                html = text.decode("utf-8", errors="ignore")
                batch = self._parse_search(html)
                for p in batch:
                    if p.paper_id not in self._processed_ids:
                        papers.append(p)
                        self._processed_ids.add(p.paper_id)
            except Exception as e:
                self.log("WARNING", f"RePEc search parse error: {e}")

        # Also fetch from NEP finance series
        nep_finance = self._fetch_nep_series("fin", max_results - len(papers))
        for p in nep_finance:
            if p.paper_id not in self._processed_ids:
                papers.append(p)
                self._processed_ids.add(p.paper_id)

        self.log("INFO", f"Fetched {len(papers)} papers from RePEc")
        return papers[:max_results]

    def _fetch_nep_series(self, topic: str, limit: int) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        url = f"https://nep.repec.org/{topic}.php"
        text = download_with_retry(url, timeout=30)
        if not text:
            return papers
        try:
            html = text.decode("utf-8", errors="ignore")
            papers = self._parse_nep(html)[:limit]
        except Exception as e:
            self.log("WARNING", f"NEP parse error: {e}")
        return papers

    def _parse_search(self, html: str) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        # Extract article/item blocks
        item_pattern = re.compile(
            r'<div[^>]*class=["\'][^"\']*(?:item|result|paper)[^"\']*["\'][^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE
        )
        for m in item_pattern.finditer(html):
            block = m.group(1)
            paper = self._parse_item(block)
            if paper:
                papers.append(paper)
        return papers

    def _parse_nep(self, html: str) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        # Find links to papers
        links = re.findall(
            r'href=["\']([^"\']*(?:repec|ideas)[^"\']*(?:paper|pdf)[^"\']*)["\']',
            html, re.IGNORECASE
        )
        for link in links[:50]:
            if not link.startswith("http"):
                link = "https://nep.repec.org/" + link.lstrip("/")
            detail = self._fetch_paper(link)
            if detail:
                papers.append(detail)
                if self.rate_limiter:
                    self.rate_limiter.wait()
        return papers

    def _parse_item(self, block: str) -> Optional[PaperInfo]:
        title_m = re.search(r'<a[^>]*href=["\'][^"\']+["\'][^>]*>(.*?)</a>', block, re.DOTALL)
        title = self._strip_tags(title_m.group(1)) if title_m else "N/A"

        authors_m = re.findall(r'<a[^>]*author[^>]*>(.*?)</a>', block, re.IGNORECASE)
        authors = [self._strip_tags(a).strip() for a in authors_m if a.strip()]

        url_m = re.search(r'href=["\']([^"\']+)["\']', block)
        url = url_m.group(1) if url_m else ""

        pid_m = re.search(r'papernum=(\d+)', url)
        paper_id = pid_m.group(1) if pid_m else self._strip_tags(title)[:50]

        return PaperInfo(
            paper_id=paper_id,
            title=title,
            abstract="",
            authors=authors,
            source="repec",
            url=url,
            categories=["finance"],
        )

    def _fetch_paper(self, url: str) -> Optional[PaperInfo]:
        text = download_with_retry(url, timeout=30)
        if not text:
            return None
        try:
            html = text.decode("utf-8", errors="ignore")
            return self._parse_paper_page(html, url)
        except Exception:
            return None

    def _parse_paper_page(self, html: str, base_url: str) -> Optional[PaperInfo]:
        title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        title = self._strip_tags(title_m.group(1)) if title_m else "N/A"

        abs_m = re.search(
            r'(?:abstract|summary)[:\s]*</(?:div|p)[^>]*>\s*(.*?)(?:<div|<p|$)',
            html, re.DOTALL | re.IGNORECASE
        )
        abstract = self._strip_tags(abs_m.group(1)) if abs_m else ""

        authors_m = re.findall(
            r'<a[^>]*class=["\'][^"\']*author[^"\']*["\'][^>]*>(.*?)</a>',
            html, re.IGNORECASE
        )
        authors = [self._strip_tags(a).strip() for a in authors_m if a.strip()]

        pid_m = re.search(r'papernum=(\d+)', base_url)
        paper_id = pid_m.group(1) if pid_m else "unknown"

        return PaperInfo(
            paper_id=paper_id,
            title=title,
            abstract=abstract,
            authors=authors,
            source="repec",
            url=base_url,
            categories=["finance"],
        )

    @staticmethod
    def _strip_tags(text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text).strip()
