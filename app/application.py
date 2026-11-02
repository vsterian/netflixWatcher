"""Module providing confirmation for Netflix Household update"""
import imaplib
import email
import re
import time
import os
import signal
from imapclient import IMAPClient
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Error as BrowserError, TimeoutError as BrowserTimeout
from logger import setup_logger
from metrics import Metrics


load_dotenv()
NETFLIX_LOGIN = os.getenv('NETFLIX_LOGIN')
NETFLIX_PASSWORD = os.getenv('NETFLIX_PASSWORD')
EMAIL_IMAP = os.getenv('EMAIL_IMAP', 'imap.gmail.com')
EMAIL_LOGIN = os.getenv('EMAIL_LOGIN')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
NETFLIX_EMAIL_SENDER = os.getenv('NETFLIX_EMAIL_SENDER')

# Set up logger
logger = setup_logger()
metrics = Metrics()
_browser = None
_page = None
_playwright = None
CONTROL_TIMEOUT_MS = 10000
BUTTON_TIMEOUT_MS = 5000
LOGIN = 'input[name="userLoginId"]'
PASSWORD = 'input[name="password"]'
TOGGLE = 'button[data-uia="login-toggle-button"]'
HOUSEHOLD = 'button[data-uia="set-primary-location-action"]'
INVALID = 'h1:text-is("This link is no longer valid")'
SUCCESS = 'h1:text-is("You’ve updated your Netflix Household")'


def get_missing_env_vars():
    """Returns list of required env vars that are missing or empty."""
    required_env_vars = {
        'NETFLIX_LOGIN': NETFLIX_LOGIN,
        'NETFLIX_PASSWORD': NETFLIX_PASSWORD,
        'EMAIL_LOGIN': EMAIL_LOGIN,
        'EMAIL_PASSWORD': EMAIL_PASSWORD,
        'NETFLIX_EMAIL_SENDER': NETFLIX_EMAIL_SENDER,
    }
    return [name for name, value in required_env_vars.items() if not value]



def extract_links(text):
    """Finds all https links"""
    url_pattern = r'https?://\S+'
    urls = re.findall(url_pattern, text)
    return urls

def login_to_netflix(page):
    """Preserve authenticated controls, password login and code-only refusal."""
    if not NETFLIX_LOGIN or not NETFLIX_PASSWORD:
        logger.error("Missing Netflix credentials; cannot perform login")
        return False
    try:
        page.locator(f'{LOGIN}:visible, {TOGGLE}:visible, {HOUSEHOLD}:visible, {INVALID}:visible, {SUCCESS}:visible').first.wait_for(
            state="visible", timeout=CONTROL_TIMEOUT_MS
        )
        if any(page.locator(selector).is_visible() for selector in (HOUSEHOLD, INVALID, SUCCESS)):
            logger.info("Netflix confirmation controls available; login not required")
            return True
        if not page.locator(LOGIN).is_visible():
            page.locator(TOGGLE).click(timeout=CONTROL_TIMEOUT_MS)
            page.locator(LOGIN).wait_for(state="visible", timeout=CONTROL_TIMEOUT_MS)
        if not page.locator(PASSWORD).is_visible() and page.locator('button[data-uia="continue-button"]').is_visible():
            logger.error("Netflix requires email-code sign-in; password login unavailable")
            return False
        page.locator(PASSWORD).wait_for(state="visible", timeout=CONTROL_TIMEOUT_MS)
        page.locator(LOGIN).fill(NETFLIX_LOGIN)
        page.locator(PASSWORD).fill(NETFLIX_PASSWORD)
        page.locator(PASSWORD).press("Enter")
        logger.info("Submitted Netflix password login")
        return True
    except BrowserTimeout:
        logger.error("Netflix login or confirmation controls not ready")
        return False


def close_browser():
    """Close warm browser and Playwright transport even after a failed launch."""
    global _browser, _page, _playwright
    browser, playwright = _browser, _playwright
    _browser = _page = _playwright = None
    metrics.set("netflix_browser_warm", 0)
    for resource, method in ((browser, 'close'), (playwright, 'stop')):
        if resource is not None:
            try:
                getattr(resource, method)()
            except Exception:
                logger.warning("Browser cleanup failed")


def get_page():
    """Reuse one volatile browser/page, rebuilding dead or closed sessions."""
    global _browser, _page, _playwright
    if _browser is not None:
        try:
            if _browser.is_connected() and not _page.is_closed():
                _page.evaluate("1")
                return _page
        except Exception:
            pass
        close_browser()
    started = time.monotonic()
    for attempt in range(2):
        try:
            _playwright = sync_playwright().start()
            _browser = _playwright.chromium.launch(
                channel="chromium", headless=True, timeout=30000,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            _page = _browser.new_page()
            _page.set_default_timeout(CONTROL_TIMEOUT_MS)
            _page.set_default_navigation_timeout(30000)
            break
        except Exception as exception:
            close_browser()
            if attempt or not isinstance(exception, BrowserError):
                metrics.update(netflix_browser_available=0, netflix_browser_last_start_timestamp_seconds=time.time())
                metrics.increment("netflix_browser_start_failure_total")
                raise
            logger.warning("Browser startup failed; retrying once")
            time.sleep(2)
    metrics.update(
        netflix_browser_warm=1,
        netflix_browser_start_duration_seconds=time.monotonic() - started,
        netflix_browser_available=1,
        netflix_browser_last_start_timestamp_seconds=time.time(),
    )
    metrics.increment("netflix_browser_start_success_total")
    return _page


def open_link_with_browser(body):
    """Confirm once, recognize terminal pages and retain only healthy browser state."""
    started = time.monotonic()
    if not body:
        logger.warning("Email body is empty; skipping browser flow")
        metrics.workflow_finished(False, time.monotonic() - started)
        return "Empty email body", None
    for link in extract_links(body):
        if "update-primary-location" not in link:
            continue
        logger.info("Found update link")
        page = None
        succeeded = False
        try:
            metrics.set("netflix_workflow_stage", 2)
            page = get_page()
            navigated = time.monotonic()
            page.goto(link, wait_until="domcontentloaded")
            logger.info("Opened Netflix update link")
            metrics.set("netflix_navigation_duration_seconds", time.monotonic() - navigated)
            metrics.set("netflix_workflow_stage", 3)
            if not login_to_netflix(page):
                content = page.content()
                metrics.workflow_finished(False, time.monotonic() - started)
                return "Netflix login failed", content
            metrics.set("netflix_workflow_stage", 4)
            page.locator(f'{HOUSEHOLD}:visible, {INVALID}:visible, {SUCCESS}:visible').first.wait_for(
                state="visible", timeout=BUTTON_TIMEOUT_MS
            )
            if not page.locator(INVALID).is_visible() and not page.locator(SUCCESS).is_visible():
                page.locator(HOUSEHOLD).click(timeout=BUTTON_TIMEOUT_MS)
                page.locator(f'{SUCCESS}:visible, {INVALID}:visible').first.wait_for(
                    state="visible", timeout=CONTROL_TIMEOUT_MS
                )
            if page.locator(INVALID).is_visible():
                content = page.content()
                metrics.workflow_finished(False, time.monotonic() - started)
                return "This link is no longer valid", content
            content = page.content()
            succeeded = True
            logger.info("Netflix Household update succeeded")
            metrics.workflow_finished(True, time.monotonic() - started)
            return "Success", content
        except BrowserTimeout:
            logger.error("Timeout waiting for Netflix confirmation")
            metrics.workflow_finished(False, time.monotonic() - started)
            return "Timeout waiting for Netflix confirmation", None
        except Exception as exception:
            if page is None:
                metrics.set("netflix_browser_available", 0)
            # Playwright exceptions can include URLs and fill values in call logs.
            logger.error("Netflix browser workflow failed", extra={"error_type": type(exception).__name__})
            metrics.workflow_finished(False, time.monotonic() - started)
            return "Browser workflow failed: " + type(exception).__name__, None
        finally:
            if succeeded:
                try:
                    page.goto("about:blank", wait_until="domcontentloaded")
                except Exception:
                    close_browser()
            else:
                close_browser()
    metrics.workflow_finished(False, time.monotonic() - started)
    return "Netflix update link not found", None


def fetch_last_unseen_email(mail):
    """Process unseen Household messages on the existing UID-based connection."""
    started = time.monotonic()
    message_ids = mail.search(['UNSEEN', 'FROM', NETFLIX_EMAIL_SENDER])
    metrics.poll_success(0, time.monotonic() - started)
    for message_id in message_ids:
        data = mail.fetch([message_id], ['BODY.PEEK[]'])
        raw_email = data.get(message_id, {}).get(b'BODY[]')
        if raw_email is None:
            raise imaplib.IMAP4.error("IMAP response missing message body")
        msg = email.message_from_bytes(raw_email)
        if not msg.get('Subject', '').startswith("Important: How to update your Netflix Household"):
            continue
        logger.info("Email identified as relevant")
        metrics.increment("netflix_matching_emails_total")
        metrics.set("netflix_matching_emails_pending", 1)
        try:
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    body = payload.decode(part.get_content_charset() or 'utf-8', errors='replace') if payload else None
                    mail.add_flags([message_id], [b'\\Seen'])
                    open_link_with_browser(body)
                    break
        finally:
            metrics.set("netflix_matching_emails_pending", 0)


def watch_mailbox():
    """Reuse authenticated IMAP, reconcile after bounded IDLE waits, reconnect on errors."""
    while True:
        mail = None
        started = time.monotonic()
        try:
            missing = get_missing_env_vars()
            if missing:
                raise ValueError("Missing required environment variables: " + ", ".join(missing))
            mail = IMAPClient(EMAIL_IMAP, timeout=30)
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            mail.select_folder('INBOX')
            if not mail.has_capability('IDLE'):
                raise imaplib.IMAP4.error("Mailbox does not support IDLE")
            metrics.set("netflix_imap_connected", 1)
            logger.info("IMAP connected; IDLE enabled")
            while True:
                started = time.monotonic()
                fetch_last_unseen_email(mail)
                try:
                    get_page()
                except Exception:
                    logger.warning("Browser warmup failed; will retry")
                mail.idle()
                metrics.set("netflix_imap_idle_active", 1)
                try:
                    mail.idle_check(timeout=10)
                finally:
                    mail.idle_done()
                    metrics.set("netflix_imap_idle_active", 0)
        except Exception as exception:
            logger.warning("IMAP session failed; reconnecting", extra={"error_type": type(exception).__name__})
            metrics.poll_failure(time.monotonic() - started)
        finally:
            metrics.update(netflix_imap_connected=0, netflix_imap_idle_active=0)
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass
        time.sleep(20)


def stop_watcher(_signum, _frame):
    """Let the main finally block close the warm browser on container stop."""
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_watcher)
    metrics.update(service_up=1)
    try:
        watch_mailbox()
    finally:
        close_browser()
        metrics.set("service_up", 0)
