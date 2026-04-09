"""Paper storage and automatic cleanup to save disk space."""
import os
import time
import shutil
from pathlib import Path
from typing import Optional
import requests
from src.scrapers.base import PaperInfo
from src.utils import download_with_retry, safe_filename


class PaperStorage:

    def __init__(self, download_dir: Path, max_size_mb: int = 50,
                 auto_cleanup: bool = True, logger=None):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.auto_cleanup = auto_cleanup
        self.logger = logger
        self._downloaded_files: list[Path] = []

    def log(self, level: str, msg: str) -> None:
        if self.logger:
            getattr(self.logger, level.lower())(msg)
        else:
            print(f"[PaperStorage] {msg}")

    def download_paper(self, paper: PaperInfo) -> Optional[Path]:
        """Download a paper PDF to disk. Returns path or None."""
        if not paper.pdf_url:
            return None

        filename = safe_filename(paper.paper_id) + ".pdf"
        filepath = self.download_dir / filename

        # Check file size limit
        if paper.paper_id:
            total_size = self._total_downloaded_size()
            if total_size > self.max_size_bytes * 5:
                self.log("WARNING", f"Storage near limit ({total_size / 1024 / 1024:.1f}MB), cleaning up old papers")
                self.cleanup_old_papers(keep_fraction=0.3)

        if filepath.exists() and filepath.stat().st_size > 0:
            self.log("INFO", f"Paper already downloaded: {filename}")
            return filepath

        self.log("INFO", f"Downloading: {paper.title[:60]} -> {filename}")
        content = download_with_retry(paper.pdf_url, timeout=60, stream=True)
        if content is None:
            self.log("WARNING", f"Failed to download: {paper.pdf_url}")
            return None

        # Check size before saving
        if len(content) > self.max_size_bytes:
            self.log("WARNING", f"Paper too large ({len(content)/1024/1024:.1f}MB > {self.max_size_bytes/1024/1024}MB), skipping")
            return None

        with open(filepath, "wb") as f:
            f.write(content)
        self._downloaded_files.append(filepath)
        self.log("INFO", f"Saved {filepath} ({len(content)/1024/1024:.2f}MB)")
        return filepath

    def extract_text_from_pdf(self, filepath: Path) -> Optional[str]:
        """Extract text from PDF for email extraction."""
        try:
            import subprocess
            # Try pdftotext
            result = subprocess.run(
                ["pdftotext", str(filepath), "-"],
                capture_output=True, timeout=30
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            self.log("WARNING", "pdftotext not found, trying PyPDF2")
        except Exception as e:
            self.log("WARNING", f"pdftotext error: {e}")

        # Fallback: PyPDF2
        try:
            import PyPDF2
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages[:5]:  # Only first 5 pages
                    text += page.extract_text() or ""
                return text
        except Exception:
            pass

        return None

    def cleanup_paper(self, filepath: Path) -> bool:
        """Delete a downloaded paper file immediately to save space."""
        try:
            if filepath.exists():
                size = filepath.stat().st_size
                filepath.unlink()
                self.log("INFO", f"Deleted paper {filepath.name} ({size/1024:.1f}KB)")
                if filepath in self._downloaded_files:
                    self._downloaded_files.remove(filepath)
                return True
        except Exception as e:
            self.log("WARNING", f"Failed to delete {filepath}: {e}")
        return False

    def cleanup_old_papers(self, keep_fraction: float = 0.3) -> int:
        """Delete oldest papers, keeping only a fraction of storage."""
        files = sorted(
            self.download_dir.glob("*.pdf"),
            key=lambda f: f.stat().st_mtime
        )
        keep_count = int(len(files) * keep_fraction)
        deleted = 0
        for f in files[:-keep_count] if keep_count > 0 else files:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
        if deleted:
            self.log("INFO", f"Cleaned up {deleted} old paper files")
        return deleted

    def _total_downloaded_size(self) -> int:
        total = 0
        for f in self.download_dir.glob("*.pdf"):
            try:
                total += f.stat().st_size
            except Exception:
                pass
        return total

    def disk_usage(self) -> dict:
        total = self._total_downloaded_size()
        count = len(list(self.download_dir.glob("*.pdf")))
        return {
            "total_mb": round(total / 1024 / 1024, 2),
            "file_count": count,
            "limit_mb": self.max_size_bytes / 1024 / 1024,
        }
