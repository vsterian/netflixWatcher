import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import application
from metrics import Metrics
from test_metrics import values


class EmptyMailbox:
    def login(self, username, password):
        return "OK", []

    def select(self, mailbox):
        return "OK", []

    def search(self, charset, query):
        return "OK", [b""]

    def close(self):
        pass

    def logout(self):
        pass


class MatchingMailbox(EmptyMailbox):
    def search(self, charset, query):
        return "OK", [b"1"]

    def fetch(self, message_id, query):
        message = (
            b"Subject: Important: How to update your Netflix Household\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"https://example.invalid/update-primary-location/private"
        )
        return "OK", [(b"RFC822", message)]

    def store(self, message_id, flags, value):
        return "OK", []


class ApplicationMetricsTest(unittest.TestCase):
    def test_empty_mailbox_is_healthy_idle(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            replacement = Metrics(path)
            configured = {
                "NETFLIX_LOGIN": "configured",
                "NETFLIX_PASSWORD": "configured",
                "EMAIL_LOGIN": "configured",
                "EMAIL_PASSWORD": "configured",
                "NETFLIX_EMAIL_SENDER": "configured",
            }
            patches = [patch.object(application, name, value) for name, value in configured.items()]
            with patch.object(application, "metrics", replacement), patch.object(
                application.imaplib, "IMAP4_SSL", return_value=EmptyMailbox()
            ):
                for current_patch in patches:
                    current_patch.start()
                try:
                    application.fetch_last_unseen_email()
                finally:
                    for current_patch in patches:
                        current_patch.stop()

            published = values(path)
            self.assertEqual(published["netflix_imap_poll_success"], 1)
            self.assertEqual(published["netflix_matching_emails_pending"], 0)
            self.assertEqual(published["netflix_workflow_stage"], 0)

    def test_selenium_start_failure_is_exported_without_url(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            replacement = Metrics(path)
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver,
                "Chrome",
                side_effect=RuntimeError("driver unavailable"),
            ):
                result, _ = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/private"
                )

            published = values(path)
            self.assertIn("error", result.lower())
            self.assertEqual(published["netflix_selenium_available"], 0)
            self.assertEqual(published["netflix_selenium_start_failure_total"], 1)
            self.assertEqual(published["netflix_workflow_failure_total"], 1)
            self.assertNotIn("example.invalid", path.read_text(encoding="utf-8"))

    def test_matching_email_count_and_pending_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            replacement = Metrics(path)
            configured = {
                "NETFLIX_LOGIN": "configured",
                "NETFLIX_PASSWORD": "configured",
                "EMAIL_LOGIN": "configured",
                "EMAIL_PASSWORD": "configured",
                "NETFLIX_EMAIL_SENDER": "configured",
            }
            patches = [patch.object(application, name, value) for name, value in configured.items()]
            with patch.object(application, "metrics", replacement), patch.object(
                application.imaplib, "IMAP4_SSL", return_value=MatchingMailbox()
            ), patch.object(application, "open_link_with_selenium", return_value=("Success", None)):
                for current_patch in patches:
                    current_patch.start()
                try:
                    application.fetch_last_unseen_email()
                finally:
                    for current_patch in patches:
                        current_patch.stop()

            published = values(path)
            self.assertEqual(published["netflix_matching_emails_total"], 1)
            self.assertEqual(published["netflix_matching_emails_pending"], 0)


if __name__ == "__main__":
    unittest.main()
