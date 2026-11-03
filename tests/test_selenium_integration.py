"""Run the same offline confirmation fixtures with native Selenium."""
import json
from unittest.mock import patch
import test_browser_integration as fixtures
from selenium_browser import SeleniumBrowser

application = fixtures.application
values = fixtures.values


class SeleniumParityTests(fixtures.BrowserParityTests):
    def setUp(self):
        super().setUp()
        self.backend = SeleniumBrowser(self.metrics, application.logger,
                                       'fixture-user', 'fixture-password', application.STATE_SCRIPT)

    def tearDown(self):
        self.backend.close()
        super().tearDown()

    def run_case(self, case):
        result = self.backend.run(self.base + case, 'selenium-fixture')
        if result[0] != 'Success':
            self.assertIsNone(self.backend.driver)
        return result

    def assert_success(self, case):
        result, content = self.run_case(case)
        self.assertEqual(result, 'Success')
        self.assertIn(fixtures.UPDATED, content)
        self.assertEqual(self.clicked[case], 1)
        self.assertEqual(self.backend.driver.current_url, 'about:blank')
        self.assertEqual(values(self.metrics.path)['netflix_workflow_last_success'], 1)

    def test_already_updated_page_is_success_without_second_click(self):
        self.assertEqual(self.run_case('already-success')[0], 'Success')
        self.assertEqual(sum(self.clicked.values()), 0)
        self.assertIsNotNone(self.backend.driver)
        self.assertEqual(self.metrics.get('netflix_workflow_last_clicked'), 0)

    def test_missing_credentials_prevent_browser_login(self):
        self.backend.password = None
        self.assertEqual(self.run_case('authenticated')[0], 'Netflix login failed')
        self.assertEqual(sum(self.clicked.values()), 0)

    def test_success_reuses_browser_and_context_cookies(self):
        self.assert_success('authenticated')
        driver = self.backend.driver
        driver.get(self.base + 'authenticated')
        driver.add_cookie({'name': 'fixture-session', 'value': 'retained'})
        self.assert_success('password')
        self.assertIs(self.backend.driver, driver)
        driver.get(self.base + 'authenticated')
        self.assertEqual(driver.get_cookie('fixture-session')['value'], 'retained')
        self.assertEqual(self.metrics.get('netflix_browser_start_success_total'), 1)

    def test_real_closed_page_and_disconnected_browser_recover(self):
        old = self.backend.get_browser()
        old.close()
        fresh = self.backend.get_browser()
        self.assertIsNot(old, fresh)
        fresh.quit()
        recovered = self.backend.get_browser()
        recovered.get(self.base + 'authenticated')
        self.assertTrue(self.backend.visible('household'))
        self.assertEqual(self.metrics.get('netflix_browser_start_success_total'), 3)

    def test_real_navigation_failure_is_sanitized_and_recovers(self):
        with self.assertLogs(application.logger, level='INFO') as output:
            result, _ = self.backend.run('http://127.0.0.1:1/update-primary-location/private', 'fixture')
        self.assertIn('failed', result)
        self.assertNotIn('http://', result + str(output.output))
        self.assertIsNone(self.backend.driver)
        self.assert_success('authenticated')

    def test_blank_page_cleanup_failure_discards_successful_browser(self):
        driver = self.backend.get_browser()
        navigate = driver.get
        def get(url):
            if url == 'about:blank':
                raise RuntimeError('fixture failure')
            return navigate(url)
        with patch.object(driver, 'get', side_effect=get):
            self.assertEqual(self.run_case('authenticated')[0], 'Success')
        self.assertIsNone(self.backend.driver)
        self.assertEqual(self.metrics.get('netflix_workflow_success_total'), 1)

    def test_timeout_diagnostics_report_phase_without_page_secrets(self):
        self.cases['private-no-result'] = fixtures.button('private-no-result', None) + '<h1>private-user private-password https://private.invalid/token</h1>'
        with self.assertLogs(application.logger, level='INFO') as captured:
            self.assertIn('Timeout', self.run_case('private-no-result')[0])
        events = [r for r in captured.records if r.msg == 'Netflix browser trace']
        self.assertTrue(all(r.engine == 'selenium' for r in events))
        self.assertEqual(events[-1].outcome, 'timeout')
        self.assertEqual(events[-1].phase, 'confirmation_result')
        self.assertEqual(sum(r.event == 'click_completed' for r in events), 1)
        state = next(r.browser_state for r in events if r.event == 'timeout_state')
        self.assertTrue(state['household_present'])
        self.assertEqual(self.clicked['private-no-result'], 1)
        exported = '\n'.join(application.logger.handlers[0].formatter.format(r) for r in events)
        for secret in ('private-user', 'private-password', 'https://', 'token'):
            self.assertNotIn(secret, exported)

    def test_network_and_console_diagnostics_are_sanitized(self):
        self.cases['private-no-result'] = fixtures.button('private-no-result', None)
        driver = self.backend.get_browser()
        events = [
            {"message": json.dumps({"message": {"method": "Network.requestWillBeSent", "params": {
                "requestId": "fetch", "type": "Fetch", "documentURL": "https://netflix.invalid/private-token",
                "request": {"url": "https://netflix.invalid/private-token", "method": "POST"}}}})},
            {"message": json.dumps({"message": {"method": "Network.responseReceived", "params": {
                "requestId": "fetch", "type": "Fetch", "response": {"status": 503,
                "url": "https://netflix.invalid/private-token"}}}})},
            {"message": json.dumps({"message": {"method": "Network.requestWillBeSent", "params": {
                "requestId": "failed", "type": "Script", "documentURL": "https://netflix.invalid/private-token",
                "request": {"url": "https://cdn.invalid/private-token.js", "method": "GET"}}}})},
            {"message": json.dumps({"message": {"method": "Network.loadingFailed", "params": {
                "requestId": "failed", "errorText": "net::ERR_CONNECTION_RESET"}}})},
            {"message": json.dumps({"message": {"method": "Network.requestWillBeSent", "params": {
                "requestId": "aborted", "type": "Document", "documentURL": "https://netflix.invalid/private-token",
                "request": {"url": "https://netflix.invalid/private-token", "method": "GET"}}}})},
            {"message": json.dumps({"message": {"method": "Network.loadingFailed", "params": {
                "requestId": "aborted", "errorText": "net::ERR_ABORTED", "canceled": True}}})},
        ]
        reads = {"performance": 0, "browser": 0}

        def get_log(kind):
            reads[kind] += 1
            if kind == "performance" and reads[kind] == 2:
                return events
            if kind == "browser" and reads[kind] == 2:
                return [{"level": "SEVERE", "message": "private-token browser error"}]
            return []

        with patch.object(driver, "get_log", side_effect=get_log), \
                self.assertLogs(application.logger, level="INFO") as captured:
            self.assertIn("Timeout", self.run_case("private-no-result")[0])
        records = [r for r in captured.records if r.msg == "Netflix browser trace"]
        self.assertTrue(any(r.event == "request_failed" and r.error_code == "net::ERR_CONNECTION_RESET" for r in records))
        self.assertTrue(any(r.event == "request_aborted" for r in records))
        self.assertTrue(any(r.event == "http_error" and r.status == 503 for r in records))
        self.assertTrue(any(r.event == "browser_console_error" for r in records))
        self.assertEqual(records[-1].request_failures, 1)
        self.assertEqual(records[-1].http_errors, 1)
        self.assertEqual(records[-1].browser_console_errors, 1)
        exported = "\n".join(application.logger.handlers[0].formatter.format(r) for r in records)
        for secret in ("netflix.invalid", "cdn.invalid", "private-token", "https://"):
            self.assertNotIn(secret, exported)
