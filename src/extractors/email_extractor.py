"""Author email extraction from various sources - optimized batch version."""
import re
import time
import concurrent.futures
from typing import Optional
from src.scrapers.base import PaperInfo
from src.utils import download_with_retry
from .orcid_client import OrcidEmailFinder


class EmailExtractor:

    EMAIL_SECTION_KEYWORDS = [
        "correspondence", "corresponding", "contact", "author information",
        "author details", "email", "e-mail", "联系方式", "通讯作者",
    ]

    def __init__(self, rate_limiter=None, scholarly_client=None, orcid_client=None):
        self.rate_limiter = rate_limiter
        self.scholarly = scholarly_client
        self.orcid = orcid_client or OrcidEmailFinder(rate_limiter)
        self._email_cache: dict[str, list[str]] = {}
        self._crossref_author_url = "https://api.crossref.org/works/{doi}"

    def extract_from_paper(self, paper: PaperInfo) -> list[str]:
        """Extract emails from paper metadata and web pages."""
        emails: list[str] = []

        text_to_search = f"{paper.title} {paper.abstract} {' '.join(paper.authors)}"
        found = self._find_emails(text_to_search)
        emails.extend(found)

        if paper.url:
            page_text = self._fetch_page_text(paper.url)
            if page_text:
                found_page = self._find_emails(page_text)
                emails.extend(found_page)
                mailto = re.findall(r'href=["\']mailto:([^"\']+)["\']', page_text, re.IGNORECASE)
                emails.extend(mailto)

        if paper.source == "arxiv":
            arxiv_emails = self._fetch_arxiv_html_emails(paper.paper_id)
            emails.extend(arxiv_emails)

        if paper.source == "crossref" and paper.paper_id.startswith("10."):
            crossref_emails = self._fetch_crossref_author_emails(paper.paper_id)
            emails.extend(crossref_emails)

        return list(set(self._normalize_email(e) for e in emails if self._is_valid_email(e)))

    def _fetch_page_text(self, url: str) -> Optional[str]:
        if self.rate_limiter:
            self.rate_limiter.wait()
        text = download_with_retry(url, timeout=20)
        if text:
            try:
                return text.decode("utf-8", errors="ignore")
            except Exception:
                pass
        return None

    def _fetch_arxiv_html_emails(self, paper_id: str) -> list[str]:
        emails: list[str] = []
        clean_id = paper_id.split("v")[0]
        url = f"https://arxiv.org/abs/{clean_id}"
        text = self._fetch_page_text(url)
        if text:
            emails.extend(self._find_emails(text))
            mailto = re.findall(r'href=["\']mailto:([^"\']+)["\']', text, re.IGNORECASE)
            emails.extend(mailto)
        return emails

    def _fetch_crossref_author_emails(self, doi: str) -> list[str]:
        emails: list[str] = []
        url = self._crossref_author_url.format(doi=doi)
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; finance-email-crawler/1.0; mailto:research@example.com)"
        }
        text = download_with_retry(url, timeout=20, headers=headers)
        if not text:
            return []
        try:
            import json
            data = json.loads(text.decode("utf-8"))
            msg = data.get("message", {})
            for author in msg.get("author", []):
                email = author.get("email")
                if email and "@" in email:
                    emails.append(email)
                orcid = author.get("ORCID", "")
                if orcid:
                    orcid_email = self.orcid.find_email_by_orcid(orcid)
                    if orcid_email:
                        emails.append(orcid_email)
        except Exception:
            pass
        return emails

    @staticmethod
    def _find_emails(text: str) -> list[str]:
        if not text:
            return []
        pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
        return [e.lower() for e in pattern.findall(text)]

    @staticmethod
    def _normalize_email(email: str) -> str:
        email = email.strip().lower()
        email = re.sub(r"^mailto:", "", email)
        email = re.sub(r'\?.*$', '', email)
        return email

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        if not email or "@" not in email:
            return False
        bad_patterns = ["example", "test", "noreply", "no-reply", "anonymous", "dummy"]
        for bp in bad_patterns:
            if bp in email.lower():
                return False
        if not re.match(r'^[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}$', email):
            return False
        return True


class AuthorDB:
    """JSON-backed database of known authors and their emails."""

    def __init__(self, authors_file):
        import json
        self.path = authors_file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def _save(self) -> None:
        import json
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def add_author(self, name: str, email: str, source: str = "", paper_id: str = "",
                   paper_authors: list[str] = None, author_position: int = 0) -> bool:
        """
        Add an author with their email.
        Only add if this is the first author OR if the email is truly unique to them.
        """
        key = name.strip().lower()
        if key not in self.data:
            self.data[key] = {
                "name": name.strip(),
                "emails": [],
                "papers": [],
                "sources": [],
            }

        # Deduplicate
        if email and email not in self.data[key]["emails"]:
            self.data[key]["emails"].append(email)

        if paper_id and paper_id not in self.data[key]["papers"]:
            self.data[key]["papers"].append(paper_id)

        if source and source not in self.data[key]["sources"]:
            self.data[key]["sources"].append(source)

        self._save()
        return True

    def deduplicate_shared_emails(self) -> int:
        """
        Remove entries where the same email is shared by many different authors.
        Keep only the first author (typically first author) for each email.
        Returns number of removed entries.
        """
        import json
        email_to_names: dict[str, list[str]] = {}
        for key, val in self.data.items():
            for email in val.get("emails", []):
                if email not in email_to_names:
                    email_to_names[email] = []
                email_to_names[email].append(key)

        removed = 0
        for email, names in email_to_names.items():
            # If same email for > 2 different name keys, only keep first alphabetically
            if len(names) > 2:
                names_sorted = sorted(names)
                keep_key = names_sorted[0]
                for nk in names_sorted[1:]:
                    self.data.pop(nk, None)
                    removed += 1

        self._save()
        return removed

    def get_authors_with_emails(self) -> list[dict]:
        return [
            {"name": v["name"], "email": v["emails"][0], "all_emails": v["emails"],
             "papers": v["papers"], "sources": v["sources"]}
            for v in self.data.values()
            if v["emails"]
        ]

    def count(self) -> int:
        return sum(1 for v in self.data.values() if v["emails"])
