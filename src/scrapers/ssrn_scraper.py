"""SSRN scraper - scrapes SSRN preprints in finance."""
import re
import json
import time
from typing import Optional
from src.scrapers.base import BaseScraper, PaperInfo
from src.utils import download_with_retry, RateLimiter


class SSRNScraper(BaseScraper):

    BASE_URL = "https://api.ssrn.com/api/v1"

    def __init__(self, rate_limiter=None, **kwargs):
        super().__init__(**kwargs)
        self.rate_limiter = rate_limiter
        self._processed_ids: set[str] = set()

    def fetch_papers(self, max_results: int = 100, **kwargs) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        self.log("INFO", "Fetching SSRN papers via search API")

        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; quant-crawler/1.0)",
        }

        # Search for quantitative finance papers
        search_terms = [
            "quantitative finance",
            "portfolio optimization",
            "factor pricing",
            "machine learning finance",
            "options pricing",
            "risk management",
            "algorithmic trading",
        ]

        for term in search_terms:
            if len(papers) >= max_results:
                break

            encoded_term = term.replace(" ", "+")
            url = (
                f"https://www.ssrn.com/en/index.cfm/jfe-api/"
                f"search?searchtxt={encoded_term}"
                f"&btnF=Search&siteAreaNavKey%3ASearch%3D"
                f"&startAtPage=1"
            )

            text = download_with_retry(url, timeout=30, headers=headers)
            if not text:
                continue

            try:
                html = text.decode("utf-8", errors="ignore")
                batch = self._parse_html(html, term)
                for p in batch:
                    if p.paper_id not in self._processed_ids:
                        papers.append(p)
                        self._processed_ids.add(p.paper_id)
            except Exception as e:
                self.log("WARNING", f"Parse error for term '{term}': {e}")

            if self.rate_limiter:
                self.rate_limiter.wait()

        # Also try the Open Access repository
        papers.extend(self._fetch_open_access(max_results - len(papers)))

        self.log("INFO", f"Fetched {len(papers)} papers from SSRN")
        return papers[:max_results]

    def _fetch_open_access(self, limit: int) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        url = "https://www.ssrn.com/mnav/indexNavBars/OL/RePEcOpeApi.cfm"
        text = download_with_retry(url, timeout=30)
        if not text:
            return papers

        try:
            html = text.decode("utf-8", errors="ignore")
            # Extract paper links
            link_pattern = re.compile(r'href=["\']([^"\']*(?:q-fin|quant|finance)[^"\']*papers[^"\']*)["\']', re.IGNORECASE)
            links = link_pattern.findall(html)
            for link in links[:limit]:
                if "ssrn.com" not in link:
                    link = "https://www.ssrn.com" + link
                detail = self._fetch_paper_detail(link)
                if detail:
                    papers.append(detail)
                    if len(papers) >= limit:
                        break
                if self.rate_limiter:
                    self.rate_limiter.wait()
        except Exception as e:
            self.log("WARNING", f"Open access fetch error: {e}")
        return papers

    def _fetch_paper_detail(self, url: str) -> Optional[PaperInfo]:
        text = download_with_retry(url, timeout=30)
        if not text:
            return None
        try:
            html = text.decode("utf-8", errors="ignore")
            return self._parse_paper_page(html, url)
        except Exception:
            return None

    def _parse_html(self, html: str, search_term: str) -> list[PaperInfo]:
        papers: list[PaperInfo] = []
        # Extract paper blocks - SSRN uses various structures
        # Try to find paper IDs in links
        id_pattern = re.compile(r'/(\d{6,})/', re.IGNORECASE)
        url_pattern = re.compile(r'href=["\']([^"\']*(?:ssrn\.com[^"\']*)[^"\']*)["\']', re.IGNORECASE)

        urls = set()
        for m in id_pattern.finditer(html):
            pid = m.group(1)
            urls.add(f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={pid}")

        for url in list(urls)[:10]:
            detail = self._fetch_paper_detail(url)
            if detail:
                papers.append(detail)
        return papers

    def _parse_paper_page(self, html: str, base_url: str) -> Optional[PaperInfo]:
        # Extract title
        title_m = re.search(r'<h1[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        if not title_m:
            title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
        title = self._strip_tags(title_m.group(1)) if title_m else "N/A"

        # Extract abstract
        abs_m = re.search(
            r'(?:abstract|summary)[:\s]*</(?:div|p|span)[^>]*>\s*(.*?)(?:<div|<p|<hr|$)',
            html, re.DOTALL | re.IGNORECASE
        )
        abstract = self._strip_tags(abs_m.group(1)) if abs_m else ""

        # Extract authors
        authors = []
        author_matches = re.findall(
            r'<a[^>]+href=["\'][^"\']*author[^"\']*["\'][^>]*>(.*?)</a>',
            html, re.IGNORECASE
        )
        for a in author_matches[:10]:
            name = self._strip_tags(a).strip()
            if name and len(name) < 100 and "author" not in name.lower():
                authors.append(name)

        # Extract paper ID from URL
        pid_m = re.search(r'abstract_id[=_](\d+)', base_url)
        paper_id = pid_m.group(1) if pid_m else "unknown"

        return PaperInfo(
            paper_id=paper_id,
            title=title,
            abstract=abstract,
            authors=authors,
            source="ssrn",
            url=base_url,
            pdf_url=base_url.replace("papers.cfm", "download"),
            categories=["finance"],
        )

    @staticmethod
    def _strip_tags(text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text).strip()
