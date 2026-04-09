#!/usr/bin/env python3
"""
Email sender - loads authors from the crawl and sends outreach emails.
"""
import csv
import sys
import argparse
import time
from pathlib import Path
from string import Formatter

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv, dotenv_values
load_dotenv(BASE_DIR / ".env")

from src.utils.config import cfg
from src.utils import setup_logger, load_json, RateLimiter
from src.emailer.sender import EmailSender, EmailQueue, FreemailSender


PLAIN_TEMPLATE = """Dear {name},

I came across your research on quantitative finance and found your work on {paper_title} particularly impressive.

Our team is working on advancing quantitative trading strategies and portfolio optimization techniques. We believe your expertise aligns well with what we're building.

Would you be open to a brief conversation to explore potential collaboration opportunities? We frequently collaborate with leading researchers in asset pricing, algorithmic trading, and financial machine learning.

If you're interested, I'd love to share more about our work and discuss how we might work together.

Best regards,
[Your Name]
Quant Finance Research Team
"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">
<p>Dear {name},</p>
<p>I came across your research on quantitative finance and found your work on <strong>{paper_title}</strong> particularly impressive.</p>
<p>Our team is working on advancing <strong>quantitative trading strategies</strong> and <strong>portfolio optimization</strong> techniques. We believe your expertise aligns well with what we're building.</p>
<p>Would you be open to a brief conversation to explore potential collaboration opportunities? We frequently collaborate with leading researchers in:</p>
<ul>
  <li>Asset pricing & factor models</li>
  <li>Algorithmic & high-frequency trading</li>
  <li>Financial machine learning</li>
  <li>Risk management & derivatives</li>
</ul>
<p>If you're interested, I'd love to share more about our work.</p>
<p>Best regards,<br>[Your Name]<br>Quant Finance Research Team</p>
</body>
</html>
"""


DEFAULT_FREEMAIL_ENV = Path("/home/user/图片/openreg/.env")
DEFAULT_ITICK_POOL = Path("/home/user/图片/itick_autoreg/accounts/itick_latest.csv")


class SenderPool:
    def __init__(self, emails: list[str]):
        self.emails = emails
        self.index = 0

    def next_email(self) -> str:
        if not self.emails:
            raise ValueError("Sender pool is empty")
        email = self.emails[self.index % len(self.emails)]
        self.index += 1
        return email

    def size(self) -> int:
        return len(self.emails)


def format_template(template: str, context: dict) -> str:
    values = {}
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            values[field_name] = context.get(field_name, "")
    return template.format(**values)


def render_templates(
    name: str,
    paper_title: str,
    subject_template: str | None = None,
    plain_template: str | None = None,
    html_template: str | None = None,
):
    context = {
        "name": name,
        "paper_title": paper_title[:80],
        "first_name": name.split()[-1] if name else "",
    }
    subject = format_template(
        subject_template or "Research Collaboration Opportunity in Quantitative Finance",
        context,
    )
    body = format_template(plain_template or PLAIN_TEMPLATE, context)
    html = format_template(html_template or HTML_TEMPLATE, context)
    return subject, body, html


def load_freemail_config(env_path: Path) -> dict:
    values = dotenv_values(env_path)
    api_url = str(values.get("FREEMAIL_API") or values.get("WORKER_DOMAIN") or "").strip()
    if api_url and not api_url.startswith("http"):
        api_url = f"https://{api_url}"
    return {
        "api_url": api_url.rstrip("/"),
        "api_key": str(values.get("FREEMAIL_API_KEY") or values.get("FREEMAIL_TOKEN") or "").strip(),
        "from_email": str(values.get("FREEMAIL_FROM_EMAIL") or f"data@{values.get('MAIL_DOMAIN', 'ai-tool.indevs.in')}").strip(),
        "from_name": str(values.get("FREEMAIL_FROM_NAME") or "Quant Finance Research").strip(),
    }


def load_sender_pool(csv_path: Path) -> list[str]:
    emails: list[str] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if not row:
                continue
            email = row[0].strip()
            if "@" in email:
                emails.append(email)
    seen = set()
    deduped = []
    for email in emails:
        if email not in seen:
            seen.add(email)
        deduped.append(email)
    return deduped


def normalize_authors(authors_payload) -> list[dict]:
    if isinstance(authors_payload, list):
        return authors_payload
    if isinstance(authors_payload, dict):
        return list(authors_payload.values())
    return []


def extract_author_email(author: dict) -> str:
    direct_email = str(author.get("email") or "").strip()
    if "@" in direct_email:
        return direct_email

    emails = author.get("emails", [])
    if isinstance(emails, str):
        for email in [part.strip() for part in emails.split(",")]:
            if "@" in email:
                return email
        return ""

    if isinstance(emails, list):
        for email in emails:
            value = str(email or "").strip()
            if "@" in value:
                return value

    return ""


def build_campaign_sender(backend: str, smtp_config: dict, freemail_config: dict, sender_pool: SenderPool | None):
    rate_limiter = RateLimiter()
    if backend == "freemail":
        if not freemail_config.get("api_url") or not freemail_config.get("api_key"):
            raise ValueError("Freemail backend requires FREEMAIL_API and FREEMAIL_API_KEY/FREEMAIL_TOKEN")
        sender = FreemailSender(
            freemail_config["api_url"],
            freemail_config["api_key"],
            freemail_config["from_email"],
            freemail_config["from_name"],
            rate_limiter,
        )
        return sender, {
            "backend": "freemail",
            "default_from_email": freemail_config["from_email"],
            "sender_pool_size": sender_pool.size() if sender_pool else 0,
        }

    sender = EmailSender(
        smtp_config["host"],
        smtp_config["port"],
        smtp_config["user"],
        smtp_config["password"],
        rate_limiter,
    )
    return sender, {
        "backend": "smtp",
        "default_from_email": smtp_config["user"],
        "sender_pool_size": 0,
    }


def send_campaign(
    sender,
    authors_file,
    backend_name,
    from_name,
    sender_pool=None,
    max_emails=50,
    delay=5,
    dry_run=True,
    subject_template=None,
    plain_template=None,
    html_template=None,
    progress_callback=None,
):
    logger = setup_logger("email_sender", cfg.LOG_FILE)
    queue = EmailQueue(cfg.EMAIL_QUEUE_FILE)

    def emit(level: str, message: str):
        log_method = getattr(logger, level)
        log_method(message)
        if progress_callback:
            progress_callback(level.upper(), message)

    authors = normalize_authors(load_json(authors_file))
    emit("info", f"Loaded {len(authors)} authors from {authors_file}")

    sent = 0
    failed = 0

    for author in authors:
        email = extract_author_email(author)
        name = author.get("name", "")
        papers = author.get("papers", [])
        paper_title = papers[0] if papers else "quantitative finance"

        if not email or "@" not in email:
            continue

        if dry_run:
            active_from = sender_pool.next_email() if sender_pool else getattr(sender, "from_email", "")
            emit("info", f"[DRY RUN] Would send to: {name} <{email}> via {backend_name} from {active_from}")
            sent += 1
            if sent >= max_emails:
                emit("info", f"Reached max emails limit ({max_emails})")
                break
            continue

        if queue.pending_count() > 0:
            item = queue.dequeue()
            if item:
                email = item["email"]
                name = item["name"]

        subject, body, html = render_templates(
            name=name,
            paper_title=paper_title,
            subject_template=subject_template,
            plain_template=plain_template,
            html_template=html_template,
        )
        active_from = sender_pool.next_email() if sender_pool else None

        success = sender.send_email(
            email,
            subject,
            body,
            html,
            from_name=from_name,
            from_email=active_from,
        )
        if success:
            queue.mark_done(email)
            sent += 1
            actual_from = active_from or getattr(sender, "from_email", getattr(sender, "user", ""))
            emit("info", f"Sent: {actual_from} -> {name} <{email}> via {backend_name}")
        else:
            queue.mark_failed(email)
            failed += 1
            actual_from = active_from or getattr(sender, "from_email", getattr(sender, "user", ""))
            error_detail = getattr(sender, "last_error", "") or "unknown error"
            emit("warning", f"Failed: {actual_from} -> {name} <{email}> via {backend_name} | {error_detail}")
            if "未配置 Resend API Key" in error_detail:
                emit("error", "Freemail 后端未配置 Resend API Key，停止当前批次")
                break

        if sent >= max_emails:
            emit("info", f"Reached max emails limit ({max_emails})")
            break

        time.sleep(delay)

    emit("info", f"Campaign done: {sent} sent, {failed} failed")
    print(f"\nResults: {sent} sent, {failed} failed, {queue.pending_count()} remaining")
    return {
        "sent": sent,
        "failed": failed,
        "remaining": queue.pending_count(),
    }


def main():
    parser = argparse.ArgumentParser(description="Send outreach emails to researchers")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry run (don't actually send)")
    parser.add_argument("--live", action="store_true",
                        help="Actually send emails (requires --dry-run off)")
    parser.add_argument("--max", type=int, default=50,
                        help="Max emails to send")
    parser.add_argument("--delay", type=int, default=5,
                        help="Seconds between emails")
    parser.add_argument("--authors", type=str, default=None,
                        help="Authors JSON file (default: data/authors/authors.json)")
    parser.add_argument("--backend", choices=["smtp", "freemail"], default="smtp",
                        help="Delivery backend")
    parser.add_argument("--freemail-env", type=str, default=str(DEFAULT_FREEMAIL_ENV),
                        help="Path to OpenReg freemail .env")
    parser.add_argument("--from-pool", type=str, default=None,
                        help="CSV file containing rotating sender addresses")
    parser.add_argument("--from-name", type=str, default=None,
                        help="Override sender display name")
    parser.add_argument("--subject-template", type=str, default=None,
                        help="Override subject template")
    parser.add_argument("--plain-template-file", type=str, default=None,
                        help="Path to plain text template file")
    parser.add_argument("--html-template-file", type=str, default=None,
                        help="Path to HTML template file")
    args = parser.parse_args()

    authors_file = Path(args.authors) if args.authors else cfg.AUTHOR_DATA_FILE
    dry_run = not args.live
    freemail_config = load_freemail_config(Path(args.freemail_env))
    sender_pool = None
    if args.from_pool:
        pool_emails = load_sender_pool(Path(args.from_pool))
        if not pool_emails:
            raise ValueError(f"No valid sender emails found in pool: {args.from_pool}")
        sender_pool = SenderPool(pool_emails)

    sender, meta = build_campaign_sender(
        backend=args.backend,
        smtp_config={
            "host": cfg.SMTP_HOST,
            "port": cfg.SMTP_PORT,
            "user": cfg.SMTP_USER,
            "password": cfg.SMTP_PASSWORD,
        },
        freemail_config=freemail_config,
        sender_pool=sender_pool,
    )
    from_name = args.from_name or freemail_config["from_name"] if args.backend == "freemail" else args.from_name or "Quant Finance Research"
    plain_template = Path(args.plain_template_file).read_text(encoding="utf-8") if args.plain_template_file else None
    html_template = Path(args.html_template_file).read_text(encoding="utf-8") if args.html_template_file else None

    print(f"=" * 60)
    print(f"  Email Campaign")
    print(f"  ===============================")
    print(f"  Authors file  : {authors_file}")
    print(f"  Max emails   : {args.max}")
    print(f"  Mode         : {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"  Backend      : {meta['backend']}")
    print(f"  Sender       : {meta['default_from_email']}")
    print(f"  Sender pool  : {meta['sender_pool_size']}")
    if meta["backend"] == "smtp":
        print(f"  SMTP         : {cfg.SMTP_HOST}:{cfg.SMTP_PORT}")
    else:
        print(f"  Freemail API : {freemail_config['api_url']}")
    print("=" * 60)

    send_campaign(
        sender,
        authors_file,
        meta["backend"],
        from_name,
        sender_pool=sender_pool,
        max_emails=args.max,
        delay=args.delay,
        dry_run=dry_run,
        subject_template=args.subject_template,
        plain_template=plain_template,
        html_template=html_template,
    )


if __name__ == "__main__":
    main()
