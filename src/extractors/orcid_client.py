"""ORCID API - most reliable way to find academic author emails."""
import re
import time
from typing import Optional
from src.utils import download_with_retry


class OrcidEmailFinder:

    """Use ORCID API to find author emails. Requires ORCID IDs."""

    API_BASE = "https://pub.orcid.org/v3.0"

    def __init__(self, rate_limiter=None):
        self.rate_limiter = rate_limiter

    def find_email_by_orcid(self, orcid_id: str) -> Optional[str]:
        """Fetch email from ORCID public API given an ORCID ID."""
        if not orcid_id or len(orcid_id) < 10:
            return None

        # Normalize ORCID (remove hyphens)
        orcid_clean = orcid_id.replace("-", "").strip()
        if len(orcid_clean) == 16:
            orcid_clean = f"{orcid_clean[0:4]}-{orcid_clean[4:8]}-{orcid_clean[8:12]}-{orcid_clean[12:16]}"

        url = f"{self.API_BASE}/{orcid_clean}/person"
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; finance-email-crawler/1.0)",
        }

        if self.rate_limiter:
            time.sleep(0.5)

        text = download_with_retry(url, timeout=20, headers=headers)
        if not text:
            return None

        try:
            import json
            data = json.loads(text.decode("utf-8"))
            emails = data.get("emails", {}).get("email", [])
            for entry in emails:
                email = entry.get("email", "")
                verified = entry.get("verified", False)
                primary = entry.get("primary", False)
                # Prefer verified primary emails
                if email and "@" in email and verified:
                    return email
            # Fall back to any email
            for entry in emails:
                email = entry.get("email", "")
                if email and "@" in email:
                    return email
        except Exception:
            pass

        return None

    def find_email_by_name(self, name: str) -> Optional[str]:
        """Search ORCID by author name and try to get email."""
        if not name or len(name) < 5:
            return None

        # Search ORCID
        parts = name.strip().split()
        if len(parts) < 2:
            return None

        given = parts[0]
        family = parts[-1]
        url = (
            f"{self.API_BASE}/search/?"
            f"q=given-name:{given}+AND+family-name:{family}"
            f"&rows=5"
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; finance-email-crawler/1.0)",
        }

        if self.rate_limiter:
            time.sleep(1.0)

        text = download_with_retry(url, timeout=20, headers=headers)
        if not text:
            return None

        try:
            import json
            data = json.loads(text.decode("utf-8"))
            hits = data.get("result", [])
            if not hits:
                return None
            # Get first ORCID result
            first = hits[0].get("orcid-identifier", {})
            orcid = first.get("uri", "").split("/")[-1]
            if orcid:
                return self.find_email_by_orcid(orcid)
        except Exception:
            pass

        return None
