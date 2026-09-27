import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

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
        self.stored = (message_id, flags, value)
        return "OK", []


class FailedSearchMailbox(EmptyMailbox):
    def search(self, charset, query):
        return "NO", []


class ImmediateWait:
    def __init__(self, driver):
        self.driver = driver

    def until(self, condition):
        result = condition(self.driver)
        if not result:
            raise application.TimeoutException()
        return result


class ApplicationMetricsTest(unittest.TestCase):
    def test_delayed_netflix_login_form_gets_credentials(self):
        email_field = Mock()
        password_field = Mock()
        driver = Mock()
        driver.find_element.side_effect = [
            application.NoSuchElementException(),
            application.NoSuchElementException(),
            application.NoSuchElementException(),
            email_field,
        ]
        driver.find_elements.side_effect = [[email_field], [password_field]]

        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ):
            self.assertTrue(application.login_to_netflix(driver))

        email_field.send_keys.assert_called_once_with("configured")
        password_field.send_keys.assert_any_call("configured")
        password_field.send_keys.assert_any_call(application.Keys.RETURN)

    def test_login_toggle_waits_for_password_form(self):
        toggle, email_field, password_field = Mock(), Mock(), Mock()
        driver = Mock()
        driver.find_element.return_value = toggle
        driver.find_elements.side_effect = [[], [], [toggle], [password_field]]
        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.side_effect = [True, [email_field]]
            self.assertTrue(application.login_to_netflix(driver))
        toggle.click.assert_called_once_with()
        email_field.send_keys.assert_called_once_with("configured")
        password_field.send_keys.assert_any_call("configured")

    def test_authenticated_page_requires_household_control(self):
        household_button = Mock()
        driver = Mock()
        driver.find_element.side_effect = [
            application.NoSuchElementException(),
            application.NoSuchElementException(),
            household_button,
        ]
        driver.find_elements.return_value = []
        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.side_effect = lambda condition: condition(driver)
            self.assertTrue(application.login_to_netflix(driver))
        self.assertEqual(driver.find_element.call_count, 3)

    def test_login_fails_when_controls_do_not_appear(self):
        driver = Mock()
        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.side_effect = application.TimeoutException()
            self.assertFalse(application.login_to_netflix(driver))

    def test_login_fails_without_credentials(self):
        with patch.object(application, "NETFLIX_LOGIN", None), patch.object(
            application, "NETFLIX_PASSWORD", None
        ):
            self.assertFalse(application.login_to_netflix(Mock()))

    def test_login_rejects_visible_form_without_password_field(self):
        driver = Mock()
        driver.find_elements.side_effect = [[Mock()], []]
        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.return_value = True
            self.assertFalse(application.login_to_netflix(driver))

    def test_link_extraction_and_missing_environment(self):
        self.assertEqual(application.extract_links("no link"), [])
        self.assertEqual(
            application.extract_links("x https://one.example/a y http://two.example/b"),
            ["https://one.example/a", "http://two.example/b"],
        )
        with patch.multiple(application, NETFLIX_LOGIN=None, NETFLIX_PASSWORD=None,
                            EMAIL_LOGIN=None, EMAIL_PASSWORD=None, NETFLIX_EMAIL_SENDER=None):
            self.assertEqual(
                application.get_missing_env_vars(),
                ["NETFLIX_LOGIN", "NETFLIX_PASSWORD", "EMAIL_LOGIN", "EMAIL_PASSWORD", "NETFLIX_EMAIL_SENDER"],
            )
        with patch.multiple(application, NETFLIX_LOGIN="x", NETFLIX_PASSWORD="x",
                            EMAIL_LOGIN="x", EMAIL_PASSWORD="x", NETFLIX_EMAIL_SENDER="x"):
            self.assertEqual(application.get_missing_env_vars(), [])

    def test_empty_link_and_unmatched_link_fail_workflow(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement):
                self.assertEqual(application.open_link_with_selenium(""), ("Empty email body", None))
                self.assertEqual(application.open_link_with_selenium("https://example.invalid/"),
                                 ("Netflix update link not found", None))
            published = values(replacement.path)
            self.assertEqual(published["netflix_workflow_failure_total"], 2)

    def test_successful_household_confirmation(self):
        button = Mock()
        button.is_displayed.return_value = True
        button.is_enabled.return_value = True
        confirmed = Mock()
        confirmed.is_displayed.return_value = True
        driver = Mock(page_source="updated")

        def find_element(_by, selector):
            return button if "set-primary-location-action" in selector else confirmed

        driver.find_element.side_effect = find_element
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ), patch.object(application, "login_to_netflix", return_value=True), patch.object(
                application, "WebDriverWait", side_effect=lambda current_driver, timeout: ImmediateWait(current_driver)
            ):
                self.assertEqual(
                    application.open_link_with_selenium(
                        "https://example.invalid/unrelated https://example.invalid/update-primary-location/token"
                    ),
                    ("Success", "updated"),
                )
            self.assertEqual(values(replacement.path)["netflix_workflow_success_total"], 1)
            button.click.assert_called_once_with()
            driver.quit.assert_called_once_with()

    def test_stale_link_and_confirmation_timeout(self):
        stale = Mock()
        stale_driver = Mock(page_source="This link is no longer valid")
        stale_driver.find_element.side_effect = [application.NoSuchElementException(), stale]
        disabled_button = Mock()
        disabled_button.is_displayed.return_value = True
        disabled_button.is_enabled.return_value = False
        timeout_driver = Mock(page_source="sign in")

        def timeout_find_element(_by, selector):
            if "set-primary-location-action" in selector:
                return disabled_button
            raise application.NoSuchElementException()

        timeout_driver.find_element.side_effect = timeout_find_element
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", side_effect=[stale_driver, timeout_driver]
            ), patch.object(application, "login_to_netflix", return_value=True), patch.object(
                application, "WebDriverWait", side_effect=lambda driver, timeout: ImmediateWait(driver)
            ):
                result, _ = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/token"
                )
                self.assertEqual(result, "This link is no longer valid")
                result, page = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/token"
                )
                self.assertEqual(result, "Timeout waiting for Netflix confirmation")
                self.assertEqual(page, "sign in")
            self.assertEqual(values(replacement.path)["netflix_workflow_failure_total"], 2)
            stale_driver.quit.assert_called_once_with()
            timeout_driver.quit.assert_called_once_with()

    def test_browser_flow_stops_when_login_is_rejected(self):
        driver = Mock()
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ), patch.object(application, "login_to_netflix", return_value=False):
                result, _ = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/token"
                )
            self.assertIn("Netflix login failed", result)
            driver.quit.assert_called_once_with()
            self.assertEqual(values(replacement.path)["netflix_workflow_failure_total"], 1)

    def test_empty_credentials_skip_mailbox_and_report_failure(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "get_missing_env_vars", return_value=["EMAIL_LOGIN"]
            ), patch.object(application.time, "sleep"):
                application.fetch_last_unseen_email()
            self.assertEqual(values(replacement.path)["netflix_imap_poll_failure_total"], 1)

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

    def test_browser_exception_is_reported_and_driver_closed(self):
        driver = Mock()
        driver.get.side_effect = RuntimeError("controlled browser failure")
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ):
                result, page = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/private"
                )
            self.assertIn("controlled browser failure", result)
            self.assertEqual(page, driver.page_source)
            driver.quit.assert_called_once_with()
            self.assertEqual(values(replacement.path)["netflix_workflow_failure_total"], 1)

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
            mailbox = MatchingMailbox()
            patches = [patch.object(application, name, value) for name, value in configured.items()]
            with patch.object(application, "metrics", replacement), patch.object(
                application.imaplib, "IMAP4_SSL", return_value=mailbox
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
            self.assertEqual(mailbox.stored, (b"1", "+FLAGS", "\\Seen"))

    def test_imap_search_failure_is_counted(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "get_missing_env_vars", return_value=[]
            ), patch.object(application.imaplib, "IMAP4_SSL", return_value=FailedSearchMailbox()):
                application.fetch_last_unseen_email()
            self.assertEqual(values(replacement.path)["netflix_imap_poll_failure_total"], 1)

    def test_transient_imap_oserror_retries_and_recovers(self):
        mailbox = EmptyMailbox()
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "get_missing_env_vars", return_value=[]
            ), patch.object(
                application.imaplib, "IMAP4_SSL", side_effect=[OSError("temporary"), mailbox]
            ), patch.object(application.time, "sleep"):
                application.fetch_last_unseen_email()
            published = values(replacement.path)
            self.assertEqual(published["netflix_imap_poll_failure_total"], 1)
            self.assertEqual(published["netflix_imap_poll_success_total"], 1)

    def test_imap_protocol_reset_and_unexpected_errors_retry(self):
        failures = [
            application.imaplib.IMAP4.error("protocol"),
            ConnectionResetError("reset"),
            RuntimeError("unexpected"),
        ]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), TemporaryDirectory() as directory:
                replacement = Metrics(Path(directory) / "netflix.prom")
                with patch.object(application, "metrics", replacement), patch.object(
                    application, "get_missing_env_vars", return_value=[]
                ), patch.object(
                    application.imaplib, "IMAP4_SSL", side_effect=[failure, EmptyMailbox()]
                ), patch.object(application.time, "sleep"):
                    application.fetch_last_unseen_email()
                published = values(replacement.path)
                self.assertEqual(published["netflix_imap_poll_failure_total"], 1)
                self.assertEqual(published["netflix_imap_poll_success_total"], 1)


if __name__ == "__main__":
    unittest.main()
