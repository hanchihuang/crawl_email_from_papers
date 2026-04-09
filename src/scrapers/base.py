"""Base scraper interface and shared utilities."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PaperInfo:
    paper_id: str          # unique ID from source
    title: str
    abstract: str
    authors: list[str]      # raw author names
    source: str             # e.g. "arxiv", "ssrn", "repec"
    url: str
    pdf_url: Optional[str] = None
    published_date: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    raw_content: Optional[str] = None  # PDF text or HTML text

    @property
    def uid(self) -> str:
        return f"{self.source}::{self.paper_id}"


class BaseScraper(ABC):

    def __init__(self, logger=None):
        self.logger = logger

    def log(self, level: str, msg: str) -> None:
        if self.logger:
            getattr(self.logger, level.lower())(f"[{self.__class__.__name__}] {msg}")
        else:
            print(f"[{self.__class__.__name__}] [{level}] {msg}")

    @abstractmethod
    def fetch_papers(self, max_results: int = 50, **kwargs) -> list[PaperInfo]:
        """Fetch list of papers from the source."""
        ...

    def cleanup_paper(self, paper: PaperInfo) -> None:
        """Delete downloaded paper file to save space."""
        pass
