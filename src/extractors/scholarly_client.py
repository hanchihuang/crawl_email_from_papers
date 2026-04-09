"""Scholarly API wrapper for author email discovery."""
import time
import re
from typing import Optional
from src.scrapers.base import PaperInfo
from src.utils import download_with_retry


class ScholarlyClient:

    BASE_URL = "https://scholar.google.com"

    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter
        self._session = None

    def find_author_email(self, author_name: str, paper_title: str = "") -> Optional[str]:
        """Use scholarly library to find author email."""
        try:
            from scholarly import scholarly
        except ImportError:
            return None

        if self.rate_limiter:
            time.sleep(0.5)

        try:
            search_results = scholarly.search_author(author_name)
            author = next(search_results, None)
            if not author:
                return None

            filled = scholarly.fill(author, sections=["basics", "counts", "indices"])
            email = filled.get("email")
            if email and "@" in email:
                return email

            # Try to get affiliation page for email
            if filled.get("affiliation"):
                affil_email = self._search_affiliation_email(filled.get("affiliation", ""), author_name)
                if affil_email:
                    return affil_email
        except Exception:
            pass

        return None

    def _search_affiliation_email(self, affiliation: str, author_name: str) -> Optional[str]:
        """Try to find email from university directory."""
        if not affiliation:
            return None

        # Search for the university homepage
        keywords = affiliation.split("|")[0].strip().split(",")[0]
        url = f"https://scholar.google.com/citations?view_op=search_authors&mauthors={author_name}&hl=en"
        text = download_with_retry(url, timeout=20)
        if text:
            try:
                html = text.decode("utf-8", errors="ignore")
                email_pattern = re.compile(r'[\w.+%+-]+@[\w-]+\.[\w.-]+')
                emails = email_pattern.findall(html)
                for email in emails:
                    if any(x in email.lower() for x in ["edu", "ac.", "org", "univ"]):
                        return email
            except Exception:
                pass
        return None
