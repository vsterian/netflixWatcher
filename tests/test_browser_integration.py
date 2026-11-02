"""Real bundled-Chromium parity tests; no Netflix network or credentials."""
import html
import json
import sys
import threading
import unittest
from collections import Counter
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import application
from metrics import Metrics
from test_metrics import values

UPDATED = "You’ve updated your Netflix Household"
EXPIRED = "This link is no longer valid"


def button(case, outcome=UPDATED, delay=0):
    action = "fetch('/clicked/" + case + "', {method:'POST'})"
    if outcome is not None:
        heading = json.dumps('<h1>' + outcome + '</h1>')
        action += ".then(()=>setTimeout(()=>{document.body.innerHTML=" + heading + ";}," + str(delay) + "))"
    return '<button data-uia="set-primary-location-action" onclick="' + html.escape(action, quote=True) + '">Confirm</button>'


def form(case, delayed=False):
    controls = '<input name="password" type="password"><button type="submit">Sign in</button>'
    authenticated = '<h1>Enter the code we sent to your email</h1>' if case == 'post-login-code' else button(case)
    action = "event.preventDefault();fetch('/login/" + case + "',{method:'POST',body:JSON.stringify({user:document.querySelector('[name=userLoginId]').value,password:document.querySelector('[name=password]').value})}).then(r=>{document.body.innerHTML=r.ok?" + json.dumps(authenticated) + ":'<h1>Rejected</h1>';})"
    result = '<form onsubmit="' + html.escape(action, quote=True) + '"><input name="userLoginId">' + ('' if delayed else controls) + '</form>'
    if delayed:
        result += '<script>setTimeout(()=>document.querySelector("form").insertAdjacentHTML("beforeend",' + json.dumps(controls) + '),150)</script>'
    return result


class BrowserParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clicked = Counter()
        cls.logins = []
        cls.code_requests = 0
        cls.cases = {
            'authenticated': button('authenticated'),
            'delayed-controls': '<div>Loading</div><script>setTimeout(()=>document.body.innerHTML=' + json.dumps(button('delayed-controls')) + ',150)</script>',
            'delayed-result': button('delayed-result', delay=150),
            'disabled-later': button('disabled-later').replace('<button ', '<button disabled ') + '<script>setTimeout(()=>document.querySelector("button").disabled=false,150)</script>',
            'disabled-forever': button('disabled-forever').replace('<button ', '<button disabled '),
            'already-success': '<h1>' + UPDATED + '</h1>',
            'invalid-before': '<h1>' + EXPIRED + '</h1>',
            'invalid-after': button('invalid-after', EXPIRED),
            'no-result': button('no-result', None),
            'no-controls': '<p>Loading</p>',
            'hidden-controls': '<input name="userLoginId" hidden><input name="password" hidden><button data-uia="set-primary-location-action" hidden>Confirm</button>',
            'hidden-success': '<h1 hidden>' + UPDATED + '</h1>',
            'password': form('password'),
            'delayed-password': form('delayed-password', delayed=True),
            'rejected': form('rejected'),
            'post-login-code': form('post-login-code'),
            'existing-code': '<h1>Enter the code we sent to your email</h1>',
            'toggle': '<button data-uia="login-toggle-button" onclick="' + html.escape('document.body.innerHTML=' + json.dumps(form('toggle')), quote=True) + '">Use password</button>',
            'missing-password': '<input name="userLoginId">',
        }
        for name, hidden in [('code-only', '<input name="password" hidden>'), ('code-no-password', '')]:
            cls.cases[name] = '<input name="userLoginId">' + hidden + '<button data-uia="continue-button" onclick="fetch(\'/code/request\',{method:\'POST\'})">Send code</button>'

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                case = self.path.rsplit('/', 1)[-1]
                body = cls.cases.get(case, '<p>Not found</p>').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                case = self.path.rsplit('/', 1)[-1]
                status = 204
                if self.path.startswith('/clicked/'):
                    cls.clicked[case] += 1
                elif self.path.startswith('/login/'):
                    payload = json.loads(raw)
                    cls.logins.append(payload)
                    status = 200 if case != 'rejected' and payload == {'user':'fixture-user', 'password':'fixture-password'} else 401
                elif self.path == '/code/request':
                    cls.code_requests += 1
                self.send_response(status)
                self.end_headers()

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port) + '/update-primary-location/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.metrics = Metrics(Path(self.directory.name) / 'metrics.prom')
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(application, 'metrics', self.metrics))
        self.stack.enter_context(patch.object(application, 'NETFLIX_LOGIN', 'fixture-user'))
        self.stack.enter_context(patch.object(application, 'NETFLIX_PASSWORD', 'fixture-password'))
        application.close_browser()
        self.clicked.clear()
        self.logins.clear()
        type(self).code_requests = 0

    def tearDown(self):
        application.close_browser()
        self.stack.close()
        self.directory.cleanup()

    def run_case(self, case):
        return application.open_link_with_browser(self.base + case)

    def assert_success(self, case):
        result, content = self.run_case(case)
        self.assertEqual(result, 'Success')
        self.assertIn(UPDATED, content)
        self.assertEqual(self.clicked[case], 1)
        self.assertEqual(application._page.url, 'about:blank')
        self.assertEqual(values(self.metrics.path)['netflix_workflow_last_success'], 1)

    def test_authenticated_confirmation(self):
        self.assert_success('authenticated')
        self.assertEqual(values(self.metrics.path)['netflix_browser_start_success_total'], 1)

    def test_delayed_controls_and_confirmation(self):
        for case in ('delayed-controls', 'delayed-result'):
            with self.subTest(case=case): self.assert_success(case)

    def test_password_login_submits_expected_values(self):
        self.assert_success('password')
        self.assertEqual(self.logins, [{'user':'fixture-user', 'password':'fixture-password'}])

    def test_password_field_can_render_after_username(self):
        self.assert_success('delayed-password')

    def test_password_toggle_renders_login_form(self):
        self.assert_success('toggle')

    def test_email_code_only_does_not_request_code_or_fill_username(self):
        for case in ('code-only', 'code-no-password', 'existing-code'):
            with self.subTest(case=case):
                result, content = self.run_case(case)
                self.assertEqual(result, 'Netflix login failed')
                self.assertNotIn('fixture-user', content)
                self.assertEqual(self.code_requests, 0)
                self.assertIsNone(application._browser)

    def test_post_password_email_verification_stops_without_requesting_code(self):
        result, content = self.run_case('post-login-code')
        self.assertEqual(result, 'Netflix login failed')
        self.assertIn('Enter the code we sent to your email', content)
        self.assertEqual(len(self.logins), 1)
        self.assertEqual(self.code_requests, 0)
        self.assertEqual(sum(self.clicked.values()), 0)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_last_success'], 0)
        self.assertIsNone(application._browser)

    def test_missing_password_hidden_controls_and_missing_controls_fail(self):
        for case in ('missing-password', 'hidden-controls', 'no-controls'):
            with self.subTest(case=case):
                self.assertEqual(self.run_case(case)[0], 'Netflix login failed')
                self.assertIsNone(application._page)

    def test_disabled_button_becomes_actionable(self):
        self.assert_success('disabled-later')

    def test_permanently_disabled_button_times_out_without_click(self):
        self.assertIn('Timeout', self.run_case('disabled-forever')[0])
        self.assertEqual(self.clicked['disabled-forever'], 0)
        self.assertIsNone(application._browser)

    def test_invalid_link_before_click(self):
        self.assertEqual(self.run_case('invalid-before')[0], EXPIRED)
        self.assertEqual(sum(self.clicked.values()), 0)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_failure_total'], 1)

    def test_link_invalid_after_single_click(self):
        self.assertEqual(self.run_case('invalid-after')[0], EXPIRED)
        self.assertEqual(self.clicked['invalid-after'], 1)

    def test_already_updated_page_is_success_without_second_click(self):
        self.assertEqual(self.run_case('already-success')[0], 'Success')
        self.assertEqual(sum(self.clicked.values()), 0)
        self.assertIsNotNone(application._browser)

    def test_confirmation_timeout_never_clicks_twice(self):
        self.assertIn('Timeout', self.run_case('no-result')[0])
        self.assertEqual(self.clicked['no-result'], 1)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_last_success'], 0)

    def test_rejected_password_login_never_reports_success(self):
        self.assertEqual(self.run_case('rejected')[0], 'Netflix login failed')
        self.assertEqual(len(self.logins), 1)
        self.assertEqual(sum(self.clicked.values()), 0)

    def test_missing_credentials_prevent_browser_login(self):
        with patch.object(application, 'NETFLIX_PASSWORD', None):
            self.assertEqual(self.run_case('authenticated')[0], 'Netflix login failed')
        self.assertEqual(sum(self.clicked.values()), 0)

    def test_hidden_success_heading_is_not_proof(self):
        self.assertNotEqual(self.run_case('hidden-success')[0], 'Success')
        self.assertEqual(values(self.metrics.path)['netflix_workflow_success_total'], 0)

    def test_success_reuses_browser_and_context_cookies(self):
        self.assert_success('authenticated')
        browser, page = application._browser, application._page
        page.context.add_cookies([{'name':'fixture-session', 'value':'retained', 'url':self.base}])
        self.assert_success('password')
        self.assertIs(application._browser, browser)
        self.assertIs(application._page, page)
        self.assertTrue(any(cookie['name'] == 'fixture-session' for cookie in page.context.cookies()))
        self.assertEqual(values(self.metrics.path)['netflix_browser_start_success_total'], 1)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_success_total'], 2)

    def test_real_closed_page_and_disconnected_browser_recover(self):
        page = application.get_page()
        old_browser = application._browser
        page.close()
        fresh = application.get_page()
        self.assertIsNot(fresh, page)
        self.assertIsNot(application._browser, old_browser)
        application._browser.close()
        recovered = application.get_page()
        recovered.goto(self.base + 'authenticated', wait_until='domcontentloaded')
        self.assertTrue(recovered.locator(application.HOUSEHOLD).is_visible())
        self.assertEqual(values(self.metrics.path)['netflix_browser_start_success_total'], 3)

    def test_real_navigation_failure_is_sanitized_and_recovers(self):
        with self.assertLogs(application.logger, level='ERROR') as output:
            result, _ = application.open_link_with_browser('http://127.0.0.1:1/update-primary-location/private')
        self.assertIn('failed', result)
        self.assertNotIn('http://', result + str(output.output))
        self.assertIsNone(application._browser)
        self.assert_success('authenticated')

    def test_blank_page_cleanup_failure_discards_successful_browser(self):
        page = application.get_page()
        navigate = page.goto
        def goto(url, **kwargs):
            if url == 'about:blank': raise application.BrowserError('blank failed')
            return navigate(url, **kwargs)
        with patch.object(page, 'goto', side_effect=goto):
            self.assertEqual(self.run_case('authenticated')[0], 'Success')
        self.assertIsNone(application._browser)
        self.assertIsNone(application._playwright)
        self.assertEqual(values(self.metrics.path)['netflix_workflow_success_total'], 1)


if __name__ == '__main__':
    unittest.main()
