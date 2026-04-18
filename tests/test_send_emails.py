import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests
from src.utils.config import cfg
from src.emailer.sender import FreemailSender

from send_emails import (
    SenderPool,
    build_campaign_sender,
    extract_author_email,
    filter_sender_pool_by_domain,
    normalize_authors,
    render_templates,
    send_campaign,
    load_freemail_config,
    load_sender_pool,
    sender_email_domain,
)


class SendEmailsHelpersTest(unittest.TestCase):
    def test_load_freemail_config_reads_openreg_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "openreg.env"
            env_path.write_text(
                "\n".join(
                    [
                        "FREEMAIL_API=https://mail.example.com",
                        "FREEMAIL_API_KEY=test-token",
                        "FREEMAIL_FROM_EMAIL=bot@example.com",
                        "FREEMAIL_FROM_NAME=Bot Sender",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_freemail_config(env_path)

            self.assertEqual(config["api_url"], "https://mail.example.com")
            self.assertEqual(config["api_key"], "test-token")
            self.assertEqual(config["from_email"], "bot@example.com")
            self.assertEqual(config["from_name"], "Bot Sender")

    def test_load_sender_pool_reads_itick_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "itick.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "邮箱,密码,API Key",
                        "a1@ai-tool.indevs.in,pwd,key1",
                        "not-an-email,pwd,key2",
                        "a2@ai-tool.indevs.in,pwd,key3",
                    ]
                ),
                encoding="utf-8",
            )

            emails = load_sender_pool(csv_path)

            self.assertEqual(emails, ["a1@ai-tool.indevs.in", "a2@ai-tool.indevs.in"])

    def test_load_sender_pool_deduplicates_addresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "itick.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "邮箱,密码,API Key",
                        "a1@ai-tool.indevs.in,pwd,key1",
                        "a1@ai-tool.indevs.in,pwd,key1",
                        "a2@ai-tool.indevs.in,pwd,key2",
                    ]
                ),
                encoding="utf-8",
            )

            emails = load_sender_pool(csv_path)

            self.assertEqual(emails, ["a1@ai-tool.indevs.in", "a2@ai-tool.indevs.in"])

    def test_filter_sender_pool_by_domain_rejects_wrong_domain(self):
        accepted, rejected = filter_sender_pool_by_domain(
            ["ok@ai-tool.indevs.in", "bad@duck.com"],
            {"ai-tool.indevs.in"},
        )

        self.assertEqual(accepted, ["ok@ai-tool.indevs.in"])
        self.assertEqual(rejected, ["bad@duck.com"])

    def test_sender_email_domain_handles_invalid_email(self):
        self.assertEqual(sender_email_domain("bad-email"), "")
        self.assertEqual(sender_email_domain("ok@ai-tool.indevs.in"), "ai-tool.indevs.in")

    def test_sender_selection_uses_rotating_from_pool_for_freemail(self):
        pool = SenderPool(["one@ai-tool.indevs.in", "two@ai-tool.indevs.in"])

        sender, meta = build_campaign_sender(
            backend="freemail",
            smtp_config={},
            freemail_config={
                "api_url": "https://mail.example.com",
                "api_key": "token",
                "from_email": "default@ai-tool.indevs.in",
                "from_name": "Campaign Sender",
            },
            sender_pool=pool,
        )

        self.assertEqual(meta["backend"], "freemail")
        self.assertEqual(meta["default_from_email"], "default@ai-tool.indevs.in")
        self.assertEqual(meta["sender_pool_size"], 2)
        self.assertEqual(pool.next_email(), "one@ai-tool.indevs.in")
        self.assertEqual(pool.next_email(), "two@ai-tool.indevs.in")
        self.assertEqual(sender.__class__.__name__, "FreemailSender")
        self.assertEqual(sender.rate_limiter.max_emails_per_hour, cfg.MAX_EMAILS_PER_HOUR)

    def test_rate_limiter_disables_hourly_email_limit_when_zero(self):
        from src.utils import RateLimiter

        limiter = RateLimiter(max_emails_per_hour=0)
        limiter.window = [1.0, 2.0, 3.0]

        with patch("src.utils.time.sleep") as mock_sleep:
            limiter.email_wait()

        mock_sleep.assert_not_called()
        self.assertEqual(limiter.window, [1.0, 2.0, 3.0])

    def test_render_templates_uses_overrides(self):
        subject, body, html = render_templates(
            name="Alice",
            paper_title="Paper",
            subject_template="Offer for {name}",
            plain_template="Hi {name}, see {paper_title}",
            html_template="<p>{name} / {paper_title}</p>",
        )

        self.assertEqual(subject, "Offer for Alice")
        self.assertEqual(body, "Hi Alice, see Paper")
        self.assertEqual(html, "<p>Alice / Paper</p>")

    def test_normalize_authors_accepts_dict_payload(self):
        authors = normalize_authors(
            {
                "alice": {"name": "Alice", "emails": "alice@example.com", "papers": []},
                "bob": {"name": "Bob", "emails": ["bob@example.com"], "papers": []},
            }
        )

        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0]["name"], "Alice")
        self.assertEqual(authors[1]["name"], "Bob")

    def test_extract_author_email_accepts_comma_separated_emails(self):
        email = extract_author_email(
            {
                "name": "Alice",
                "emails": "alice@example.com, other@example.com",
            }
        )

        self.assertEqual(email, "alice@example.com")

    @patch("send_emails.EmailQueue")
    @patch("send_emails.setup_logger")
    def test_send_campaign_honors_max_in_dry_run(self, mock_logger_factory, mock_queue_cls):
        with tempfile.TemporaryDirectory() as tmpdir:
            authors_path = Path(tmpdir) / "authors.json"
            authors_path.write_text(
                """[
                    {"name": "A", "email": "a@example.com", "papers": []},
                    {"name": "B", "email": "b@example.com", "papers": []},
                    {"name": "C", "email": "c@example.com", "papers": []}
                ]""",
                encoding="utf-8",
            )
            logger = mock_logger_factory.return_value
            sender = object()

            send_campaign(
                sender=sender,
                authors_file=authors_path,
                backend_name="freemail",
                from_name="Tester",
                sender_pool=SenderPool(["one@ai-tool.indevs.in", "two@ai-tool.indevs.in"]),
                max_emails=2,
                delay=0,
                dry_run=True,
            )

            dry_run_calls = [call for call in logger.info.call_args_list if "[DRY RUN]" in str(call)]
            self.assertEqual(len(dry_run_calls), 2)

    @patch("send_emails.EmailQueue")
    @patch("send_emails.setup_logger")
    def test_send_campaign_honors_start_index_in_dry_run(self, mock_logger_factory, mock_queue_cls):
        with tempfile.TemporaryDirectory() as tmpdir:
            authors_path = Path(tmpdir) / "authors.json"
            authors_path.write_text(
                """[
                    {"name": "A", "email": "a@example.com", "papers": []},
                    {"name": "B", "email": "b@example.com", "papers": []},
                    {"name": "C", "email": "c@example.com", "papers": []}
                ]""",
                encoding="utf-8",
            )
            logger = mock_logger_factory.return_value

            result = send_campaign(
                sender=object(),
                authors_file=authors_path,
                backend_name="freemail",
                from_name="Tester",
                sender_pool=SenderPool(["one@ai-tool.indevs.in"]),
                start_index=2,
                max_emails=1,
                delay=0,
                dry_run=True,
            )

            self.assertEqual(result["sent"], 1)
            dry_run_messages = [str(call) for call in logger.info.call_args_list if "[DRY RUN]" in str(call)]
            self.assertEqual(len(dry_run_messages), 1)
            self.assertIn("b@example.com", dry_run_messages[0])

    @patch("send_emails.EmailQueue")
    @patch("send_emails.setup_logger")
    def test_send_campaign_reports_progress_callback(self, mock_logger_factory, mock_queue_cls):
        with tempfile.TemporaryDirectory() as tmpdir:
            authors_path = Path(tmpdir) / "authors.json"
            authors_path.write_text(
                '[{"name": "A", "email": "a@example.com", "papers": []}]',
                encoding="utf-8",
            )
            events = []

            result = send_campaign(
                sender=object(),
                authors_file=authors_path,
                backend_name="freemail",
                from_name="Tester",
                sender_pool=SenderPool(["one@ai-tool.indevs.in"]),
                max_emails=1,
                delay=0,
                dry_run=True,
                progress_callback=lambda level, message: events.append((level, message)),
            )

            self.assertEqual(result["sent"], 1)
            self.assertTrue(any("[DRY RUN]" in message for _, message in events))

    def test_freemail_sender_records_http_error_detail(self):
        sender = FreemailSender(
            api_url="https://mail.example.com",
            api_key="token",
            from_email="bot@example.com",
        )

        with patch("requests.post", side_effect=requests.RequestException("connection reset")):
            success = sender.send_email(
                "a@example.com",
                "Subject",
                "Body",
                from_name="Tester",
            )

        self.assertFalse(success)
        self.assertIn("connection reset", sender.last_error)

    @patch("send_emails.EmailQueue")
    @patch("send_emails.setup_logger")
    def test_send_campaign_includes_sender_error_detail(self, mock_logger_factory, mock_queue_cls):
        class FailingSender:
            from_email = "bot@example.com"
            last_error = "HTTP 403: sender not allowed"

            def send_email(self, *args, **kwargs):
                return False

        with tempfile.TemporaryDirectory() as tmpdir:
            authors_path = Path(tmpdir) / "authors.json"
            authors_path.write_text(
                '[{"name": "A", "email": "a@example.com", "papers": []}]',
                encoding="utf-8",
            )
            mock_queue = mock_queue_cls.return_value
            mock_queue.pending_count.return_value = 0
            events = []

            result = send_campaign(
                sender=FailingSender(),
                authors_file=authors_path,
                backend_name="freemail",
                from_name="Tester",
                max_emails=1,
                delay=0,
                dry_run=False,
                progress_callback=lambda level, message: events.append((level, message)),
            )

            self.assertEqual(result["failed"], 1)
            self.assertTrue(any("sender not allowed" in message for _, message in events))

    @patch("send_emails.EmailQueue")
    @patch("send_emails.setup_logger")
    def test_send_campaign_stops_on_missing_resend_key(self, mock_logger_factory, mock_queue_cls):
        class FailingSender:
            from_email = "bot@example.com"
            last_error = "HTTP 500: 未配置 Resend API Key"

            def send_email(self, *args, **kwargs):
                return False

        with tempfile.TemporaryDirectory() as tmpdir:
            authors_path = Path(tmpdir) / "authors.json"
            authors_path.write_text(
                '[{"name": "A", "email": "a@example.com", "papers": []}, {"name": "B", "email": "b@example.com", "papers": []}]',
                encoding="utf-8",
            )
            mock_queue = mock_queue_cls.return_value
            mock_queue.pending_count.return_value = 0
            events = []

            result = send_campaign(
                sender=FailingSender(),
                authors_file=authors_path,
                backend_name="freemail",
                from_name="Tester",
                max_emails=10,
                delay=0,
                dry_run=False,
                progress_callback=lambda level, message: events.append((level, message)),
            )

            self.assertEqual(result["failed"], 1)
            self.assertTrue(any("停止当前批次" in message for _, message in events))


if __name__ == "__main__":
    unittest.main()
