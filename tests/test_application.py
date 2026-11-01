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
    def search(self, query):
        return []


class MatchingMailbox(EmptyMailbox):
    def search(self, query):
        return [1]

    def fetch(self, message_ids, query):
        message = (
            b"Subject: Important: How to update your Netflix Household\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"https://example.invalid/update-primary-location/private"
        )
        return {1: {b'BODY[]': message}}

    def add_flags(self, message_ids, flags):
        self.stored = (message_ids, flags)


class ImmediateWait:
    def __init__(self, driver):
        self.driver = driver

    def until(self, condition):
        result = condition(self.driver)
        if not result:
            raise application.TimeoutException()
        return result


class ApplicationMetricsTest(unittest.TestCase):
    def setUp(self):
        application._browser = None

    def tearDown(self):
        application._browser = None

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
        driver.find_elements.side_effect = [[email_field], []]

        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.side_effect = [True, password_field]
            self.assertTrue(application.login_to_netflix(driver))

        self.assertEqual(wait.call_count, 2)
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

    def test_email_code_sign_in_fails_without_requesting_code(self):
        email_field, hidden_password, continue_button = Mock(), Mock(), Mock()
        hidden_password.is_displayed.return_value = False
        driver = Mock()
        driver.find_elements.side_effect = [[email_field], [hidden_password], [continue_button]]
        with patch.object(application, "NETFLIX_LOGIN", "configured"), patch.object(
            application, "NETFLIX_PASSWORD", "configured"
        ), patch.object(application, "WebDriverWait") as wait:
            wait.return_value.until.return_value = True
            self.assertFalse(application.login_to_netflix(driver))
        email_field.send_keys.assert_not_called()
        continue_button.click.assert_not_called()

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
            wait.return_value.until.side_effect = [True, application.TimeoutException()]
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
            ) as chrome, patch.object(application, "login_to_netflix", return_value=True), patch.object(
                application, "WebDriverWait", side_effect=lambda current_driver, timeout: ImmediateWait(current_driver)
            ), patch.object(application.time, "sleep") as sleep:
                self.assertEqual(
                    application.open_link_with_selenium(
                        "https://example.invalid/unrelated https://example.invalid/update-primary-location/token"
                    ),
                    ("Success", "updated"),
                )
                self.assertEqual(application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/next"
                ), ("Success", "updated"))
                chrome.assert_called_once()
                sleep.assert_not_called()
            self.assertEqual(values(replacement.path)["netflix_workflow_success_total"], 2)
            self.assertEqual(button.click.call_count, 2)
            driver.quit.assert_not_called()
            driver.get.assert_any_call("about:blank")

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

    def test_link_becomes_invalid_after_one_click(self):
        button = Mock()
        button.is_displayed.return_value = True
        button.is_enabled.return_value = True
        driver = Mock(page_source="pending")
        driver.find_element.return_value = button
        button.click.side_effect = lambda: setattr(driver, "page_source", "This link is no longer valid")
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ), patch.object(application, "login_to_netflix", return_value=True), patch.object(
                application, "WebDriverWait", side_effect=lambda current_driver, timeout: ImmediateWait(current_driver)
            ):
                result, _ = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/token"
                )
            self.assertEqual(result, "This link is no longer valid")
            self.assertEqual(values(replacement.path)["netflix_workflow_failure_total"], 1)
            button.click.assert_called_once_with()

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

    def test_empty_mailbox_is_healthy_idle(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement):
                application.fetch_last_unseen_email(EmptyMailbox())
            published = values(replacement.path)
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
            ), patch.object(application, "Service"):
                result, _ = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/private"
                )

            published = values(path)
            self.assertIn("error", result.lower())
            self.assertEqual(published["netflix_selenium_available"], 0)
            self.assertEqual(published["netflix_selenium_start_failure_total"], 1)
            self.assertEqual(published["netflix_workflow_failure_total"], 1)
            self.assertNotIn("example.invalid", path.read_text(encoding="utf-8"))

    def test_transient_browser_start_failure_retries_and_cleans_service(self):
        driver = Mock()
        for failures in (1, 2):
            with self.subTest(failures=failures), TemporaryDirectory() as directory:
                replacement = Metrics(Path(directory) / "netflix.prom")
                services = [Mock(), Mock()]
                outcomes = [application.WebDriverException("service unavailable")] * failures
                if failures == 1:
                    outcomes.append(driver)
                with patch.object(application, "metrics", replacement), patch.object(
                    application, "Service", side_effect=services
                ), patch.object(application.webdriver, "Chrome", side_effect=outcomes) as chrome, patch.object(
                    application, "login_to_netflix", return_value=False
                ), patch.object(application.time, "sleep"):
                    application.open_link_with_selenium(
                        "https://example.invalid/update-primary-location/private"
                    )
                self.assertEqual(chrome.call_count, 2)
                services[0].stop.assert_called_once_with()
                published = values(replacement.path)
                if failures == 1:
                    services[1].stop.assert_not_called()
                    driver.quit.assert_called_once_with()
                    self.assertEqual(published["netflix_selenium_start_success_total"], 1)
                else:
                    services[1].stop.assert_called_once_with()
                    self.assertEqual(published["netflix_selenium_start_failure_total"], 1)

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
            replacement = Metrics(Path(directory) / "netflix.prom")
            mailbox = MatchingMailbox()
            with patch.object(application, "metrics", replacement), patch.object(
                application, "open_link_with_selenium", return_value=("Success", None)
            ):
                application.fetch_last_unseen_email(mailbox)
            published = values(replacement.path)
            self.assertEqual(published["netflix_matching_emails_total"], 1)
            self.assertEqual(published["netflix_matching_emails_pending"], 0)
            self.assertEqual(mailbox.stored, ([1], [b'\\Seen']))

    def test_mail_body_failure_clears_pending_state(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "open_link_with_selenium", side_effect=RuntimeError("failure")
            ):
                with self.assertRaises(RuntimeError):
                    application.fetch_last_unseen_email(MatchingMailbox())
            self.assertEqual(values(replacement.path)["netflix_matching_emails_pending"], 0)

    def test_idle_reuses_connection_and_reconciles_after_notification_and_timeout(self):
        mailbox = Mock()
        mailbox.idle_check.side_effect = [[(1, b'EXISTS')], [], SystemExit()]
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "IMAPClient", return_value=mailbox
            ) as connect, patch.object(application, "get_missing_env_vars", return_value=[]), patch.object(
                application, "fetch_last_unseen_email"
            ) as scan, patch.object(application, "get_browser") as warmup:
                application._browser = Mock()
                with self.assertRaises(SystemExit):
                    application.watch_mailbox()
            connect.assert_called_once_with(application.EMAIL_IMAP, timeout=30)
            mailbox.login.assert_called_once()
            self.assertEqual(scan.call_count, 3)
            self.assertEqual(mailbox.idle_done.call_count, 3)
            mailbox.idle_check.assert_called_with(timeout=10)
            mailbox.logout.assert_called_once()
            self.assertEqual(warmup.call_count, 3)
            published = values(replacement.path)
            self.assertEqual(published["netflix_imap_connected"], 0)
            self.assertEqual(published["netflix_imap_idle_active"], 0)

    def test_connection_and_idle_failure_reconnect(self):
        for failure_at in ('connect', 'idle'):
            with self.subTest(failure_at=failure_at), TemporaryDirectory() as directory:
                replacement = Metrics(Path(directory) / "netflix.prom")
                mailbox = Mock()
                if failure_at == 'idle':
                    mailbox.idle_check.side_effect = TimeoutError("disconnected")
                    outcomes = [mailbox, SystemExit()]
                else:
                    outcomes = [TimeoutError("connect"), SystemExit()]
                with patch.object(application, "metrics", replacement), patch.object(
                    application, "IMAPClient", side_effect=outcomes
                ) as connect, patch.object(application, "get_missing_env_vars", return_value=[]), patch.object(
                    application, "fetch_last_unseen_email"
                ), patch.object(application.time, "sleep") as sleep:
                    application._browser = Mock()
                    with self.assertRaises(SystemExit):
                        application.watch_mailbox()
                self.assertEqual(connect.call_count, 2)
                sleep.assert_called_once_with(20)
                self.assertEqual(values(replacement.path)["netflix_imap_poll_failure_total"], 1)
                if failure_at == 'idle':
                    mailbox.logout.assert_called_once()
                    mailbox.idle_done.assert_called_once()

    def test_missing_credentials_do_not_connect(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "get_missing_env_vars", return_value=['EMAIL_LOGIN']
            ), patch.object(application, "IMAPClient") as connect, patch.object(
                application.time, "sleep", side_effect=SystemExit()
            ):
                with self.assertRaises(SystemExit):
                    application.watch_mailbox()
            connect.assert_not_called()
            self.assertEqual(values(replacement.path)["netflix_imap_poll_failure_total"], 1)

    def test_warm_browser_reused_and_eager_without_sleep(self):
        driver = Mock()
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ) as chrome, patch.object(application.time, "sleep") as sleep:
                self.assertIs(application.get_browser(), driver)
                self.assertIs(application.get_browser(), driver)
                chrome.assert_called_once()
                self.assertEqual(chrome.call_args.kwargs['options'].page_load_strategy, 'eager')
                sleep.assert_not_called()
                application.close_browser()
            driver.quit.assert_called_once()
            self.assertIsNone(application._browser)
            self.assertEqual(values(replacement.path)["netflix_browser_warm"], 0)

    def test_mailbox_without_idle_rejected_and_closed(self):
        mailbox = Mock()
        mailbox.has_capability.return_value = False
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "get_missing_env_vars", return_value=[]
            ), patch.object(application, "IMAPClient", return_value=mailbox), patch.object(
                application.time, "sleep", side_effect=SystemExit()
            ):
                with self.assertRaises(SystemExit):
                    application.watch_mailbox()
            mailbox.logout.assert_called_once()
            mailbox.idle.assert_not_called()
            self.assertEqual(values(replacement.path)["netflix_imap_connected"], 0)

    def test_login_select_scan_and_idle_done_errors_close_session(self):
        for method in ('login', 'select_folder', 'search', 'idle_done'):
            with self.subTest(method=method), TemporaryDirectory() as directory:
                mailbox = Mock()
                mailbox.search.return_value = []
                getattr(mailbox, method).side_effect = application.imaplib.IMAP4.error("protocol")
                replacement = Metrics(Path(directory) / "netflix.prom")
                with patch.object(application, "metrics", replacement), patch.object(
                    application, "get_missing_env_vars", return_value=[]
                ), patch.object(application, "IMAPClient", return_value=mailbox), patch.object(
                    application.time, "sleep", side_effect=SystemExit()
                ), patch.object(application, "get_browser"):
                    with self.assertRaises(SystemExit):
                        application.watch_mailbox()
                mailbox.logout.assert_called_once()
                published = values(replacement.path)
                self.assertEqual(published["netflix_imap_connected"], 0)
                self.assertEqual(published["netflix_imap_idle_active"], 0)
                self.assertEqual(published["netflix_imap_poll_failure_total"], 1)

    def test_missing_message_body_fails_without_marking_seen(self):
        mailbox = Mock()
        mailbox.search.return_value = [1]
        mailbox.fetch.return_value = {}
        with TemporaryDirectory() as directory:
            with patch.object(application, "metrics", Metrics(Path(directory) / "netflix.prom")):
                with self.assertRaises(application.imaplib.IMAP4.error):
                    application.fetch_last_unseen_email(mailbox)
        mailbox.add_flags.assert_not_called()

    def test_unrelated_subject_is_not_marked_seen_or_opened(self):
        mailbox = Mock()
        mailbox.search.return_value = [1]
        mailbox.fetch.return_value = {1: {b'BODY[]': b'Subject: Other Netflix notice\r\n\r\nbody'}}
        with TemporaryDirectory() as directory:
            with patch.object(application, "metrics", Metrics(Path(directory) / "netflix.prom")), patch.object(
                application, "open_link_with_selenium"
            ) as workflow:
                application.fetch_last_unseen_email(mailbox)
        mailbox.add_flags.assert_not_called()
        workflow.assert_not_called()

    def test_multiple_messages_use_stable_uids_and_peek(self):
        mailbox = Mock()
        mailbox.search.return_value = [11, 22]
        message = MatchingMailbox().fetch([1], [])[1][b'BODY[]']
        mailbox.fetch.side_effect = [{11: {b'BODY[]': message}}, {22: {b'BODY[]': message}}]
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application, "open_link_with_selenium", return_value=("Success", None)
            ) as workflow:
                application.fetch_last_unseen_email(mailbox)
            self.assertEqual(workflow.call_count, 2)
            self.assertEqual(mailbox.fetch.call_args_list[0].args, ([11], ['BODY.PEEK[]']))
            self.assertEqual(mailbox.fetch.call_args_list[1].args, ([22], ['BODY.PEEK[]']))
            self.assertEqual(values(replacement.path)["netflix_matching_emails_total"], 2)

    def test_browser_quit_failure_still_clears_cache(self):
        driver = Mock()
        driver.quit.side_effect = application.WebDriverException("already dead")
        application._browser = driver
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement):
                application.close_browser()
            self.assertIsNone(application._browser)
            self.assertEqual(values(replacement.path)["netflix_browser_warm"], 0)

    def test_stop_signal_uses_graceful_shutdown(self):
        with self.assertRaises(SystemExit):
            application.stop_watcher(None, None)

    def test_dead_warm_browser_rebuilt_before_navigation(self):
        old, fresh = Mock(), Mock()
        type(old).window_handles = property(lambda _self: (_ for _ in ()).throw(application.WebDriverException("dead")))
        application._browser = old
        with TemporaryDirectory() as directory:
            with patch.object(application, "metrics", Metrics(Path(directory) / "netflix.prom")), patch.object(
                application.webdriver, "Chrome", return_value=fresh
            ):
                self.assertIs(application.get_browser(), fresh)
        old.quit.assert_called_once()

    def test_dead_browser_does_not_escape_error_handling(self):
        driver = Mock()
        driver.get.side_effect = application.WebDriverException("dead")
        type(driver).page_source = property(lambda _self: (_ for _ in ()).throw(application.WebDriverException("dead")))
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement), patch.object(
                application.webdriver, "Chrome", return_value=driver
            ):
                result, page = application.open_link_with_selenium(
                    "https://example.invalid/update-primary-location/private"
                )
            self.assertIn("error", result)
            self.assertIsNone(page)
            self.assertIsNone(application._browser)
            driver.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
