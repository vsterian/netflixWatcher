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


class MailboxTests(unittest.TestCase):
    def setUp(self):
        application._browser = application._page = application._playwright = None

    def tearDown(self):
        application._browser = application._page = application._playwright = None

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


    def test_empty_mailbox_is_healthy_idle(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            with patch.object(application, "metrics", replacement):
                application.fetch_last_unseen_email(EmptyMailbox())
            published = values(replacement.path)
            self.assertEqual(published["netflix_imap_poll_success"], 1)
            self.assertEqual(published["netflix_matching_emails_pending"], 0)
            self.assertEqual(published["netflix_workflow_stage"], 0)


    def test_matching_email_count_and_pending_state(self):
        with TemporaryDirectory() as directory:
            replacement = Metrics(Path(directory) / "netflix.prom")
            mailbox = MatchingMailbox()
            with patch.object(application, "metrics", replacement), patch.object(
                application, "process_email", side_effect=lambda body, mark_seen: mark_seen()
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
                application, "process_email", side_effect=RuntimeError("failure")
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
            ) as scan, patch.object(application, "warm_browser") as warmup:
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
                ), patch.object(application, "warm_browser"), patch.object(application.time, "sleep") as sleep:
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
                ), patch.object(application, "get_page"):
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
                application, "process_email"
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
                application, "process_email", side_effect=lambda body, mark_seen: mark_seen()
            ) as workflow:
                application.fetch_last_unseen_email(mailbox)
            self.assertEqual(workflow.call_count, 2)
            self.assertEqual(mailbox.fetch.call_args_list[0].args, ([11], ['BODY.PEEK[]']))
            self.assertEqual(mailbox.fetch.call_args_list[1].args, ([22], ['BODY.PEEK[]']))
            self.assertEqual(values(replacement.path)["netflix_matching_emails_total"], 2)


    def test_stop_signal_uses_graceful_shutdown(self):
        with self.assertRaises(SystemExit):
            application.stop_watcher(None, None)


class BrowserLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.metrics = Metrics(Path(self.directory.name) / "metrics.prom")
        self.metrics_patch = patch.object(application, "metrics", self.metrics)
        self.metrics_patch.start()
        self.factory_patch = patch.object(application, "sync_playwright")
        self.factory = self.factory_patch.start()
        self.runtime = self.factory.return_value.start.return_value
        self.browser = self.runtime.chromium.launch.return_value
        self.page = self.browser.new_page.return_value
        self.browser.is_connected.return_value = True
        self.page.is_closed.return_value = False
        self.page.evaluate.return_value = {"ready_state": "complete", "react_click_handler": False}
        application._browser = application._page = application._playwright = None

    def tearDown(self):
        application.close_browser()
        self.factory_patch.stop()
        self.metrics_patch.stop()
        self.directory.cleanup()

    def test_launch_and_metrics(self):
        self.assertIs(application.get_page(), self.page)
        launch = self.runtime.chromium.launch.call_args.kwargs
        self.assertEqual(launch['channel'], 'chromium')
        self.assertTrue(launch['headless'])
        self.assertEqual(launch['timeout'], 30000)
        self.page.set_default_navigation_timeout.assert_called_once_with(30000)
        published = values(self.metrics.path)
        self.assertEqual(published['netflix_browser_available'], 1)
        self.assertEqual(published['netflix_browser_warm'], 1)
        self.assertEqual(published['netflix_browser_start_success_total'], 1)
        self.assertFalse(any('selenium' in name for name in published))

    def test_warm_page_reuse_probes_transport(self):
        self.assertIs(application.get_page(), application.get_page())
        self.runtime.chromium.launch.assert_called_once()
        self.page.locator.assert_called_once_with('html')
        self.page.locator.return_value.wait_for.assert_called_once_with(state='attached', timeout=application.CONTROL_TIMEOUT_MS)

    def test_closed_page_disconnected_browser_and_transport_error_rebuild(self):
        for failure in ('closed', 'disconnected', 'transport'):
            with self.subTest(failure=failure):
                application.close_browser()
                self.page.is_closed.return_value = False
                self.browser.is_connected.return_value = True
                self.page.locator.return_value.wait_for.side_effect = None
                application.get_page()
                starts = self.runtime.chromium.launch.call_count
                if failure == 'closed': self.page.is_closed.return_value = True
                if failure == 'disconnected': self.browser.is_connected.return_value = False
                if failure == 'transport': self.page.locator.return_value.wait_for.side_effect = application.BrowserError('dead')
                application.get_page()
                self.assertEqual(self.runtime.chromium.launch.call_count, starts + 1)

    def test_transient_launch_failure_retries_and_cleans_runtime(self):
        self.runtime.chromium.launch.side_effect = [application.BrowserError('launch'), self.browser]
        with patch.object(application.time, 'sleep') as sleep:
            self.assertIs(application.get_page(), self.page)
        sleep.assert_called_once_with(2)
        self.runtime.stop.assert_called_once()
        self.assertEqual(values(self.metrics.path)['netflix_browser_start_success_total'], 1)

    def test_exhausted_launch_failure_is_counted_once(self):
        self.runtime.chromium.launch.side_effect = application.BrowserError('launch')
        with patch.object(application.time, 'sleep'), self.assertRaises(application.BrowserError):
            application.get_page()
        self.assertEqual(self.runtime.chromium.launch.call_count, 2)
        published = values(self.metrics.path)
        self.assertEqual(published['netflix_browser_start_failure_total'], 1)
        self.assertEqual(published['netflix_browser_available'], 0)
        self.assertEqual(published['netflix_browser_warm'], 0)
        self.assertIsNone(application._playwright)

    def test_page_creation_failure_closes_partial_browser(self):
        self.browser.new_page.side_effect = [application.BrowserError('page'), self.page]
        with patch.object(application.time, 'sleep'):
            self.assertIs(application.get_page(), self.page)
        self.browser.close.assert_called_once()
        self.runtime.stop.assert_called_once()

    def test_unexpected_launch_error_not_retried(self):
        self.runtime.chromium.launch.side_effect = ValueError('configuration')
        with self.assertRaises(ValueError): application.get_page()
        self.runtime.chromium.launch.assert_called_once()
        self.assertEqual(values(self.metrics.path)['netflix_browser_start_failure_total'], 1)

    def test_runtime_start_failure_can_retry(self):
        self.factory.return_value.start.side_effect = [application.BrowserError('transport'), self.runtime]
        with patch.object(application.time, 'sleep'):
            self.assertIs(application.get_page(), self.page)
        self.assertEqual(self.factory.return_value.start.call_count, 2)

    def test_cleanup_closes_transport_even_when_browser_close_fails(self):
        application.get_page()
        self.browser.close.side_effect = application.BrowserError('closed')
        application.close_browser()
        self.runtime.stop.assert_called_once()
        self.assertIsNone(application._page)
        self.assertIsNone(application._browser)
        self.assertIsNone(application._playwright)

    def test_cleanup_is_idempotent_and_tolerates_stopped_runtime(self):
        application.get_page()
        self.runtime.stop.side_effect = application.BrowserError('stopped')
        application.close_browser()
        application.close_browser()
        self.runtime.stop.assert_called_once()

    def test_error_call_logs_do_not_expose_urls_or_fill_values(self):
        secret = 'private-password-and-token'
        self.page.goto.side_effect = application.BrowserError('fill("' + secret + '") https://example.invalid/private')
        with self.assertLogs(application.logger, level='ERROR') as output:
            result, html = application.open_link_with_browser('https://example.invalid/update-primary-location/private')
        self.assertIsNone(html)
        self.assertNotIn(secret, result + str(output.output))
        self.assertNotIn('https://', result + str(output.output))
        self.assertEqual(values(self.metrics.path)['netflix_workflow_failure_total'], 1)
        self.assertIsNone(application._browser)

    def test_startup_failure_through_workflow_is_exported(self):
        self.runtime.chromium.launch.side_effect = ValueError('configuration')
        result, html = application.open_link_with_browser('https://example.invalid/update-primary-location/private')
        self.assertIn('failed', result)
        self.assertIsNone(html)
        published = values(self.metrics.path)
        self.assertEqual(published['netflix_browser_available'], 0)
        self.assertEqual(published['netflix_workflow_failure_total'], 1)

    def test_navigation_timeout_is_failure_and_discards_browser(self):
        self.page.goto.side_effect = application.BrowserTimeout('slow')
        result, _ = application.open_link_with_browser('https://example.invalid/update-primary-location/private')
        self.assertIn('Timeout', result)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_failure_total'], 1)
        self.browser.close.assert_called_once()
        self.page.remove_listener.assert_any_call('requestfailed', unittest.mock.ANY)
        self.page.remove_listener.assert_any_call('response', unittest.mock.ANY)

    def test_content_failure_never_double_counts_terminal_outcomes(self):
        for state in ('login', 'invalid', 'success'):
            with self.subTest(state=state):
                application.close_browser()
                self.page.goto.side_effect = None
                self.page.content.side_effect = application.BrowserError('closed during snapshot')
                def locator(selector):
                    control = Mock()
                    control.is_visible.return_value = (selector == application.INVALID and state == 'invalid') or (selector == application.SUCCESS and state == 'success')
                    return control
                self.page.locator.side_effect = locator
                before = self.metrics._values['netflix_workflow_failure_total']
                with patch.object(application, 'login_to_netflix', return_value=state != 'login'):
                    result, _ = application.open_link_with_browser('https://example.invalid/update-primary-location/private')
                self.assertIn('failed', result)
                self.assertEqual(self.metrics._values['netflix_workflow_failure_total'], before + 1)
                self.assertEqual(self.metrics._values['netflix_workflow_success_total'], 0)
                self.assertIsNone(application._browser)

    def test_empty_and_unmatched_body_do_not_launch_browser(self):
        for body, result in (('', 'Empty email body'), ('https://example.invalid/unrelated', 'Netflix update link not found')):
            self.assertEqual(application.open_link_with_browser(body), (result, None))
        self.factory.assert_not_called()
        self.assertEqual(values(self.metrics.path)['netflix_workflow_failure_total'], 2)


if __name__ == '__main__':
    unittest.main()
