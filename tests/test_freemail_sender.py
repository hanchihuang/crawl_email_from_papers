import json
import unittest
from unittest.mock import MagicMock, patch

from src.emailer.sender import FreemailSender


class FreemailSenderTest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_freemail_sender_posts_api_request(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps({"success": True, "id": "msg-1"}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        sender = FreemailSender(
            api_url="https://mail.example.com",
            api_key="secret-token",
            from_email="from@ai-tool.indevs.in",
            from_name="Campaign Sender",
        )

        ok = sender.send_email(
            "to@example.com",
            "Subject",
            "Plain body",
            "<p>HTML body</p>",
            from_name="Override Name",
            from_email="pool@ai-tool.indevs.in",
        )

        self.assertTrue(ok)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://mail.example.com/api/send")
        self.assertEqual(request.headers["Authorization"], "Bearer secret-token")
        self.assertEqual(request.headers["Content-type"], "application/json")

        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["from"], "pool@ai-tool.indevs.in")
        self.assertEqual(payload["fromName"], "Override Name")
        self.assertEqual(payload["to"], "to@example.com")
        self.assertEqual(payload["subject"], "Subject")
        self.assertEqual(payload["text"], "Plain body")
        self.assertEqual(payload["html"], "<p>HTML body</p>")


if __name__ == "__main__":
    unittest.main()
