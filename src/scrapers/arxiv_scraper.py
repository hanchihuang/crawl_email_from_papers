"""arXiv scraper for high-frequency trading papers."""
import re
import time
import urllib.parse
from typing import Optional

from src.scrapers.base import BaseScraper, PaperInfo
from src.utils import download_with_retry


class ArxivScraper(BaseScraper):

    BASE_URL = "http://export.arxiv.org/api/query"

    HFT_KEYWORDS = [
        "high frequency trading", "high-frequency trading", "high frequency",
        "algorithmic trading", "algo trading", "electronic trading",
        "market microstructure", "limit order book", "order book",
        "lob", "order flow", "trade flow", "tick data",
        "ultra low latency", "low latency", "latency arbitrage",
        "statistical arbitrage", "arbitrage", "market making",
        "optimal execution", "execution cost", "execution strategy",
        "slippage", "price impact", "liquidity", "bid ask spread",
        "bid-ask spread", "quote imbalance", "microprice",
        "mid price", "mid-price", "transaction cost",
        "intraday", "tick-by-tick", "matching engine",
        "order imbalance", "fill probability",
    ]

    def __init__(self, categories: list[str], rate_limiter=None, **kwargs):
        super().__init__(**kwargs)
        self.categories = categories
        self.rate_limiter = rate_limiter
        self._processed_ids: set[str] = set()

    def fetch_papers(self, max_results: int = 200, **kwargs) -> list[PaperInfo]:
        papers: list[PaperInfo] = []

        for cat in self.categories:
            self.log("INFO", f"Fetching arXiv category: {cat}")
            page = 0
            total = 0

            while total < max_results:
                start = page * 100
                # Broader query: just the category, filter by keywords in Python
                query = f"cat:{cat}"
                params = {
                    "search_query": query,
                    "start": start,
                    "max_results": min(100, max_results - total),
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                }
                url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
                xml_text = self._fetch_url(url)
                if not xml_text:
                    break

                batch = self._parse_response(xml_text, cat)
                if not batch:
                    break

                # Post-filter: keep only high-frequency trading related papers.
                for p in batch:
                    combined = (p.title + " " + p.abstract).lower()
                    if any(kw.lower() in combined for kw in self.HFT_KEYWORDS):
                        if p.paper_id not in self._processed_ids:
                            papers.append(p)
                            self._processed_ids.add(p.paper_id)

                total += len(batch)
                page += 1

                if self.rate_limiter:
                    self.rate_limiter.wait()
                else:
                    time.sleep(self._random_sleep())

        self.log("INFO", f"Fetched {len(papers)} high-frequency trading papers from arXiv")
        return papers

    def _fetch_url(self, url: str) -> Optional[str]:
        content = download_with_retry(url, timeout=30)
        return content.decode("utf-8") if content else None

    def _parse_response(self, xml_text: str, category: str) -> list[PaperInfo]:
        import xml.etree.ElementTree as ET
        papers: list[PaperInfo] = []

        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
        except Exception:
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            paper_id_raw = entry.find("atom:id", ns)
            if paper_id_raw is None:
                continue
            paper_id = paper_id_raw.text.split("/")[-1]

            title_el = entry.find("atom:title", ns)
            title = re.sub(r"\s+", " ", title_el.text.strip()) if title_el is not None else "N/A"

            abstract_el = entry.find("atom:summary", ns)
            abstract = re.sub(r"\s+", " ", abstract_el.text.strip()) if abstract_el is not None else ""

            authors = [
                a.find("atom:name", ns).text.strip()
                for a in entry.findall("atom:author", ns)
                if a.find("atom:name", ns) is not None and a.find("atom:name", ns).text
            ]

            published_el = entry.find("atom:published", ns)
            published = published_el.text[:10] if published_el is not None else None

            # Find PDF link
            pdf_url = None
            for link_el in entry.findall("atom:link", ns):
                href = link_el.get("href", "")
                if ".pdf" in href:
                    pdf_url = href
                    break

            url = paper_id_raw.text if paper_id_raw is not None else f"https://arxiv.org/abs/{paper_id}"

            papers.append(PaperInfo(
                paper_id=paper_id,
                title=title,
                abstract=abstract,
                authors=authors,
                source="arxiv",
                url=url,
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{paper_id}.pdf",
                published_date=published,
                categories=[category],
            ))

        return papers

    @staticmethod
    def _random_sleep() -> float:
        import random
        return random.uniform(1.0, 3.0)
