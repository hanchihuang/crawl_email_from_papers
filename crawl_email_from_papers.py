#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import fitz
import requests


ARXIV_API_URL = "http://export.arxiv.org/api/query"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}
EMAIL_RE = re.compile(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", re.IGNORECASE)
OBFUSCATED_EMAIL_RE = re.compile(
    r"\b[a-z0-9._%+\-]+\s*(?:@|\(at\)|\[at\]|\sat\s)\s*[a-z0-9.\-]+\s*"
    r"(?:\.|\(dot\)|\[dot\]|\sdot\s)\s*[a-z]{2,}\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl papers from arXiv or use explicit PDF inputs, then extract author emails."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Optional explicit inputs: arXiv id, arXiv URL, direct PDF URL, local PDF path, or a .txt file",
    )
    parser.add_argument(
        "--query",
        default="",
        help="arXiv search query, for example: cat:cs.LG or all:diffusion model",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="arXiv result offset. Default: 0",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="How many papers to crawl from arXiv. Default: 10",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Only scan the first N pages of each PDF. Default: 3",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds. Default: 120",
    )
    parser.add_argument(
        "--cache-dir",
        default=".cache/pdfs",
        help="Directory for downloaded PDFs. Default: .cache/pdfs",
    )
    parser.add_argument(
        "--out",
        default="emails.csv",
        help="Output CSV path. Default: emails.csv",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional JSON output path",
    )
    return parser.parse_args()


def load_inputs(raw_inputs: list[str]) -> list[str]:
    resolved: list[str] = []
    for item in raw_inputs:
        path = Path(item)
        if path.exists() and path.is_file() and path.suffix.lower() == ".txt":
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    resolved.append(line)
        else:
            resolved.append(item)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in resolved:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def crawl_arxiv_inputs(query: str, start: int, max_results: int, timeout: int) -> list[dict]:
    params = {
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    response = requests.get(ARXIV_API_URL, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    crawled: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        id_text = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        title = re.sub(r"\s+", " ", entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            href = (link.attrib.get("href") or "").strip()
            title_attr = (link.attrib.get("title") or "").strip().lower()
            if title_attr == "pdf" or href.endswith(".pdf"):
                pdf_url = href if href.endswith(".pdf") else f"{href}.pdf"
                break
        if not pdf_url and id_text:
            pdf_url = id_text.replace("/abs/", "/pdf/") + ".pdf"
        if not pdf_url:
            continue
        crawled.append(
            {
                "input": pdf_url,
                "crawl_source": "arxiv",
                "crawl_query": query,
                "paper_id": id_text,
                "paper_title": title,
                "published": published,
            }
        )
    return crawled


def is_probably_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def looks_like_arxiv_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", value))


def build_pdf_url(item: str) -> str | None:
    if looks_like_arxiv_id(item):
        return f"https://arxiv.org/pdf/{item}.pdf"
    if "arxiv.org/abs/" in item:
        return item.replace("/abs/", "/pdf/") + ".pdf"
    if "arxiv.org/pdf/" in item:
        return item if item.endswith(".pdf") else f"{item}.pdf"
    if is_probably_url(item) and item.lower().endswith(".pdf"):
        return item
    return None


def cache_name_from_url(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    parsed = urlparse(url)
    stem = Path(parsed.path).name or "paper.pdf"
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem)
    if not stem.lower().endswith(".pdf"):
        stem = f"{stem}.pdf"
    return f"{digest}_{stem}"


def ensure_pdf(item: str, cache_dir: Path, timeout: int) -> tuple[Path, str]:
    path = Path(item).expanduser()
    if path.exists():
        return path.resolve(), "local"

    pdf_url = build_pdf_url(item)
    if not pdf_url:
        raise ValueError(f"Unsupported input: {item}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = cache_dir / cache_name_from_url(pdf_url)
    if not pdf_path.exists():
        with requests.get(pdf_url, headers=HEADERS, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            with pdf_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
    return pdf_path.resolve(), pdf_url


def normalize_email_candidate(value: str) -> str:
    text = value.lower()
    text = re.sub(r"\s*(?:\(|\[)?at(?:\)|\])?\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(?:\(|\[)?dot(?:\)|\])?\s*", ".", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*@\s*", "@", text)
    text = re.sub(r"\s*\.\s*", ".", text)
    text = text.strip(".,;:()[]{}<>\"'")
    return text


def extract_text_with_fitz(pdf_path: Path, max_pages: int) -> str:
    doc = fitz.open(pdf_path)
    pieces: list[str] = []
    for page_index, page in enumerate(doc):
        if page_index >= max_pages:
            break
        pieces.append(page.get_text("text"))
    return "\n".join(pieces).replace("\x00", " ")


def extract_text_with_pdftotext(pdf_path: Path, max_pages: int) -> str:
    cmd = [
        "pdftotext",
        "-f",
        "1",
        "-l",
        str(max_pages),
        "-layout",
        str(pdf_path),
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.replace("\x00", " ")


def extract_text(pdf_path: Path, max_pages: int) -> str:
    text = ""
    try:
        text = extract_text_with_fitz(pdf_path, max_pages)
    except Exception:
        text = ""
    if text.strip():
        return text
    return extract_text_with_pdftotext(pdf_path, max_pages)


def extract_emails(text: str) -> list[str]:
    found: set[str] = set()
    for match in EMAIL_RE.findall(text):
        found.add(normalize_email_candidate(match))
    for match in OBFUSCATED_EMAIL_RE.findall(text):
        normalized = normalize_email_candidate(match)
        if EMAIL_RE.fullmatch(normalized):
            found.add(normalized)
    return sorted(found)


def infer_title(pdf_path: Path, text: str) -> str:
    for line in text.splitlines()[:40]:
        line = re.sub(r"\s+", " ", line).strip()
        if not (10 <= len(line) <= 200):
            continue
        lowered = line.lower()
        if re.match(r"^\d", line):
            continue
        if lowered in {"abstract", "introduction", "references"}:
            continue
        if any(
            marker in lowered
            for marker in ("introduction", "related work", "references", "appendix", "preprint")
        ):
            continue
        return line
    return pdf_path.stem


def process_one(item: str | dict, cache_dir: Path, max_pages: int, timeout: int) -> dict:
    raw_input = item["input"] if isinstance(item, dict) else item
    pdf_path, source = ensure_pdf(raw_input, cache_dir, timeout)
    text = extract_text(pdf_path, max_pages=max_pages)
    emails = extract_emails(text)
    result = {
        "input": raw_input,
        "source": source,
        "pdf_path": str(pdf_path),
        "title": infer_title(pdf_path, text),
        "emails": emails,
        "email_count": len(emails),
    }
    if isinstance(item, dict):
        result.update(
            {
                "crawl_source": item.get("crawl_source", ""),
                "crawl_query": item.get("crawl_query", ""),
                "paper_id": item.get("paper_id", ""),
                "paper_title": item.get("paper_title", ""),
                "published": item.get("published", ""),
            }
        )
        if item.get("paper_title"):
            result["title"] = item["paper_title"]
    return result


def write_csv(rows: Iterable[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "input",
                "paper_id",
                "title",
                "published",
                "email_count",
                "emails",
                "crawl_source",
                "crawl_query",
                "source",
                "pdf_path",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "input": row["input"],
                    "paper_id": row.get("paper_id", ""),
                    "title": row["title"],
                    "published": row.get("published", ""),
                    "email_count": row["email_count"],
                    "emails": "; ".join(row["emails"]),
                    "crawl_source": row.get("crawl_source", ""),
                    "crawl_query": row.get("crawl_query", ""),
                    "source": row["source"],
                    "pdf_path": row["pdf_path"],
                }
            )


def main() -> int:
    args = parse_args()
    items: list[str | dict] = []
    if args.query:
        items.extend(
            crawl_arxiv_inputs(
                query=args.query,
                start=args.start,
                max_results=args.max_results,
                timeout=args.timeout,
            )
        )
    items.extend(load_inputs(args.inputs))
    if not items:
        print("No inputs provided. Use --query for arXiv crawling or pass explicit PDF inputs.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir).expanduser()
    out_path = Path(args.out).expanduser()
    json_out_path = Path(args.json_out).expanduser() if args.json_out else None
    results: list[dict] = []

    for item in items:
        try:
            result = process_one(item, cache_dir=cache_dir, max_pages=args.max_pages, timeout=args.timeout)
            results.append(result)
            email_text = ", ".join(result["emails"]) if result["emails"] else "(none)"
            print(f"[ok] {result['input']} -> {email_text}", file=sys.stderr)
        except Exception as exc:
            item_value = item["input"] if isinstance(item, dict) else item
            print(f"[error] {item_value}: {exc}", file=sys.stderr)
            results.append(
                {
                    "input": item_value,
                    "source": "",
                    "pdf_path": "",
                    "title": "",
                    "emails": [],
                    "email_count": 0,
                    "error": str(exc),
                }
            )

    write_csv(results, out_path)
    if json_out_path:
        json_out_path.parent.mkdir(parents=True, exist_ok=True)
        json_out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
