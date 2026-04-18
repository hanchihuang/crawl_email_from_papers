"""Email sender with SMTP and freemail API support."""
import time
import json
import smtplib
import ssl
import random
from urllib.parse import urlparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from pathlib import Path
from typing import Optional
import requests
from src.utils import RateLimiter, load_json, save_json


class EmailSender:

    def __init__(self, smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                 rate_limiter: Optional[RateLimiter] = None):
        self.host = smtp_host
        self.port = smtp_port
        self.user = smtp_user
        self.password = smtp_password
        self.rate_limiter = rate_limiter
        self._sent: set[str] = set()
        self.last_error = ""

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        from_name: str = "Quant Finance Research",
        from_email: Optional[str] = None,
    ) -> bool:
        """Send a single email. Returns True on success."""
        self.last_error = ""
        if to_email in self._sent:
            self.last_error = f"duplicate recipient: {to_email}"
            return False

        if self.rate_limiter:
            self.rate_limiter.email_wait()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        actual_from_email = from_email or self.user
        msg["From"] = f"{from_name} <{actual_from_email}>"
        msg["To"] = to_email
        msg["X-Priority"] = "3"

        msg.attach(MIMEText(body, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.user, self.password)
                server.sendmail(actual_from_email, [to_email], msg.as_string())
            self._sent.add(to_email)
            self.last_error = ""
            return True
        except smtplib.SMTPException as e:
            self.last_error = f"SMTP error: {e}"
            print(f"SMTP error sending to {to_email}: {e}")
            return False
        except Exception as e:
            self.last_error = f"Error: {e}"
            print(f"Error sending to {to_email}: {e}")
            return False

    def send_batch(
        self,
        recipients: list[dict],
        subject_template: str,
        body_template: str,
        body_html_template: Optional[str] = None,
        from_name: str = "Quant Finance Research",
    ) -> dict:
        """Send emails to multiple recipients. Each recipient dict has 'name' and 'email'."""
        results = {"sent": 0, "failed": 0, "skipped": 0}
        for r in recipients:
            email = r.get("email", "")
            name = r.get("name", "")
            if not email or email in self._sent:
                results["skipped"] += 1
                continue

            subject = subject_template.replace("{name}", name).replace("{first_name}", name.split()[-1])
            body = body_template.replace("{name}", name).replace("{first_name}", name.split()[-1])
            body_html = None
            if body_html_template:
                body_html = body_html_template.replace("{name}", name).replace("{first_name}", name.split()[-1])

            if self.send_email(email, subject, body, body_html, from_name):
                results["sent"] += 1
            else:
                results["failed"] += 1

            # Small random delay between emails
            time.sleep(random.uniform(2, 6))

        return results


class FreemailSender:

    def __init__(
        self,
        api_url: str,
        api_key: str,
        from_email: str,
        from_name: str = "Quant Finance Research",
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.from_email = from_email
        self.from_name = from_name
        self.rate_limiter = rate_limiter
        self._sent: set[str] = set()
        self.last_error = ""

    def _browser_headers(self) -> dict[str, str]:
        parsed = urlparse(self.api_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": origin,
            "Referer": f"{origin}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        from_name: str = "Quant Finance Research",
        from_email: Optional[str] = None,
    ) -> bool:
        self.last_error = ""
        if to_email in self._sent:
            self.last_error = f"duplicate recipient: {to_email}"
            return False

        if self.rate_limiter:
            self.rate_limiter.email_wait()

        payload = {
            "from": from_email or self.from_email,
            "fromName": from_name or self.from_name,
            "to": to_email,
            "subject": subject,
            "text": body,
        }
        if body_html:
            payload["html"] = body_html

        try:
            response = requests.post(
                f"{self.api_url}/api/send",
                json=payload,
                headers=self._browser_headers(),
                timeout=30,
            )
            response.raise_for_status()
            body_text = response.text or "{}"
            data = json.loads(body_text)
            if data.get("success", False):
                self._sent.add(to_email)
                self.last_error = ""
                return True
            self.last_error = f"API rejected: {json.dumps(data, ensure_ascii=False)}"
            print(f"Freemail API rejected {to_email}: {data}")
            return False
        except requests.HTTPError as exc:
            body_text = exc.response.text if exc.response is not None else ""
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            self.last_error = f"HTTP {status_code}: {body_text[:500]}"
            print(f"Freemail HTTP error sending to {to_email}: {status_code} {body_text[:200]}")
            return False
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            if response is not None and response.text:
                self.last_error = f"HTTP {response.status_code}: {response.text[:500]}"
            else:
                self.last_error = f"Request error: {exc}"
            print(f"Freemail request error sending to {to_email}: {self.last_error}")
            return False
        except Exception as exc:
            self.last_error = f"Error: {exc}"
            print(f"Freemail error sending to {to_email}: {exc}")
            return False


class EmailQueue:

    def __init__(self, queue_file: Path):
        self.path = queue_file
        self.queue: list[dict] = []
        self.load()

    def load(self) -> None:
        self.queue = load_json(self.path)

    def save(self) -> None:
        save_json(self.queue, self.path)

    def enqueue(self, author: dict) -> None:
        """Add author to email queue if not already queued."""
        email = author.get("email", "")
        if not email:
            return
        if not any(a.get("email") == email for a in self.queue):
            self.queue.append({
                "email": email,
                "name": author.get("name", ""),
                "all_emails": author.get("all_emails", []),
                "papers": author.get("papers", []),
                "sources": author.get("sources", []),
                "status": "pending",
                "attempts": 0,
            })
            self.save()

    def dequeue(self) -> Optional[dict]:
        self.load()
        for item in self.queue:
            if item.get("status") == "pending":
                item["status"] = "sending"
                item["attempts"] = item.get("attempts", 0) + 1
                self.save()
                return item
        return None

    def mark_done(self, email: str) -> None:
        self.load()
        for item in self.queue:
            if item.get("email") == email:
                item["status"] = "done"
                break
        self.save()

    def mark_failed(self, email: str) -> None:
        self.load()
        for item in self.queue:
            if item.get("email") == email:
                item["status"] = "failed"
                break
        self.save()

    def pending_count(self) -> int:
        self.load()
        return sum(1 for i in self.queue if i.get("status") == "pending")

    def stats(self) -> dict:
        self.load()
        pending = sum(1 for i in self.queue if i.get("status") == "pending")
        sent = sum(1 for i in self.queue if i.get("status") == "done")
        failed = sum(1 for i in self.queue if i.get("status") == "failed")
        return {"pending": pending, "sent": sent, "failed": failed, "total": len(self.queue)}
