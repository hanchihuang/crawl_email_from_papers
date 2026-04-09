import unittest
from unittest.mock import patch

from web_app import (
    JOBS,
    JOB_LOCK,
    append_job_log,
    html_to_plain_text,
    merge_form_values,
    render_page,
    run_campaign_from_form,
    snapshot_job,
)


class WebAppTest(unittest.TestCase):
    def test_html_to_plain_text_strips_tags(self):
        plain = html_to_plain_text("<h1>Title</h1><p>Hello <strong>world</strong></p>")
        self.assertEqual(plain, "Title Hello world")

    def test_render_page_includes_form_values(self):
        page = render_page(
            {
                "subject": "Hello",
                "body": "Plain body",
                "html_body": "<p>HTML body</p>",
                "backend": "freemail",
                "max_emails": "3",
                "delay": "2",
                "from_name": "Tester",
                "from_pool": "on",
                "dry_run": "on",
            },
            "Finished",
        )

        self.assertIn("Hello", page)
        self.assertIn("Plain body", page)
        self.assertIn("HTML body", page)
        self.assertIn("Finished", page)
        self.assertIn('value="freemail"', page)
        self.assertIn('id="logBox"', page)
        self.assertIn("/start", page)
        self.assertIn("/status?job_id=", page)

    def test_merge_form_values_allows_unchecked_checkboxes(self):
        values = merge_form_values(
            {
                "subject": "Hello",
                "backend": "smtp",
            }
        )

        self.assertEqual(values["subject"], "Hello")
        self.assertEqual(values["backend"], "smtp")
        self.assertNotIn("dry_run", values)
        self.assertNotIn("from_pool", values)

    @patch("web_app.send_campaign")
    @patch("web_app.build_campaign_sender")
    @patch("web_app.load_freemail_config")
    def test_run_campaign_from_form_returns_logs(self, mock_freemail, mock_builder, mock_send_campaign):
        mock_freemail.return_value = {
            "api_url": "https://mail.example.com",
            "api_key": "token",
            "from_name": "Bot Sender",
        }
        mock_builder.return_value = (object(), {"backend": "freemail"})

        def fake_send_campaign(**kwargs):
            kwargs["progress_callback"]("INFO", "Loaded authors")
            kwargs["progress_callback"]("INFO", "[DRY RUN] Would send to: A <a@example.com>")
            return {"sent": 1, "failed": 0, "remaining": 0}

        mock_send_campaign.side_effect = fake_send_campaign
        message, logs = run_campaign_from_form(
            {
                "subject": "Hello",
                "body": "Plain body",
                "html_body": "<p>HTML body</p>",
                "backend": "freemail",
                "max_emails": "1",
                "delay": "0",
                "from_name": "Tester",
                "dry_run": "on",
            }
        )

        self.assertIn("sent=1", message)
        self.assertIn("INFO | Loaded authors", logs)
        self.assertIn("Would send to", "\n".join(logs))

    @patch("web_app.send_campaign")
    @patch("web_app.build_campaign_sender")
    @patch("web_app.smtp_is_configured", return_value=False)
    @patch("web_app.load_freemail_config")
    def test_run_campaign_from_form_fails_when_no_real_backend_available(
        self,
        mock_freemail,
        mock_smtp_ready,
        mock_builder,
        mock_send_campaign,
    ):
        mock_freemail.return_value = {
            "api_url": "https://mail.example.com",
            "api_key": "token",
            "from_name": "Bot Sender",
        }
        mock_builder.return_value = (object(), {"backend": "freemail"})

        def fake_send_campaign(**kwargs):
            kwargs["progress_callback"]("WARNING", "Failed: x -> y via freemail | HTTP 500: 未配置 Resend API Key")
            kwargs["progress_callback"]("ERROR", "Freemail 后端未配置 Resend API Key，停止当前批次")
            return {"sent": 0, "failed": 1, "remaining": 0}

        mock_send_campaign.side_effect = fake_send_campaign

        with self.assertRaisesRegex(ValueError, "本地 SMTP 未配置"):
            run_campaign_from_form(
                {
                    "subject": "Hello",
                    "body": "Plain body",
                    "html_body": "<p>HTML body</p>",
                    "backend": "freemail",
                    "max_emails": "1",
                    "delay": "0",
                    "from_name": "Tester",
                }
            )

    def test_snapshot_job_returns_missing_for_unknown_job(self):
        data = snapshot_job("missing-job")

        self.assertEqual(data["status"], "missing")
        self.assertEqual(data["logs"], [])

    def test_append_job_log_updates_snapshot(self):
        with JOB_LOCK:
            JOBS["job-1"] = {
                "status": "running",
                "message": "working",
                "logs": [],
                "values": {},
            }

        append_job_log("job-1", "INFO", "Sent: a@example.com -> b@example.com")
        data = snapshot_job("job-1")

        self.assertEqual(data["status"], "running")
        self.assertIn("INFO | Sent: a@example.com -> b@example.com", data["logs"])
        with JOB_LOCK:
            JOBS.pop("job-1", None)


if __name__ == "__main__":
    unittest.main()
