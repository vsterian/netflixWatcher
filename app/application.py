"""Module providing confirmation for Netflix Household update"""
import imaplib
import email
import re
import time
import os
import signal
from imapclient import IMAPClient
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException
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

def login_to_netflix(driver):
    """Handles the login process for Netflix."""
    if not NETFLIX_LOGIN or not NETFLIX_PASSWORD:
        logger.error("Missing Netflix credentials; cannot perform login")
        return False

    try:
        WebDriverWait(driver, 10).until(EC.any_of(
            EC.visibility_of_element_located((By.NAME, 'userLoginId')),
            EC.visibility_of_element_located((By.XPATH, '//button[@data-uia="login-toggle-button"]')),
            EC.visibility_of_element_located((By.XPATH, '//button[@data-uia="set-primary-location-action"]')),
        ))
    except TimeoutException:
        logger.error("Netflix login and household controls not found")
        return False

    email_fields = driver.find_elements(By.NAME, 'userLoginId')
    password_fields = driver.find_elements(By.NAME, 'password')
    if not email_fields and driver.find_elements(By.XPATH, '//button[@data-uia="login-toggle-button"]'):
        driver.find_element(By.XPATH, '//button[@data-uia="login-toggle-button"]').click()
        email_fields = WebDriverWait(driver, 10).until(
            lambda current_driver: current_driver.find_elements(By.NAME, 'userLoginId')
        )
        password_fields = driver.find_elements(By.NAME, 'password')

    if not email_fields:
        logger.info("Netflix household controls available; login not required")
        return True
    if password_fields and not password_fields[0].is_displayed():
        continue_buttons = driver.find_elements(By.XPATH, '//button[@data-uia="continue-button"]')
        if continue_buttons:
            logger.error("Netflix requires email-code sign-in; password login unavailable")
            return False
    if not password_fields:
        try:
            password_fields = [WebDriverWait(driver, 10).until(
                EC.visibility_of_element_located((By.NAME, 'password'))
            )]
        except TimeoutException:
            logger.error("Netflix password field not found")
            return False
    if not password_fields[0].is_displayed():
        logger.error("Netflix password field not found")
        return False

    email_fields[0].send_keys(NETFLIX_LOGIN)
    logger.info("Filled in Netflix email")
    password_fields[0].send_keys(NETFLIX_PASSWORD)
    logger.info("Filled in Netflix password")
    password_fields[0].send_keys(Keys.RETURN)
    logger.info("Pressed Enter to log in")
    return True


    


def close_browser():
    """Discard failed or stopped browser, including its child processes."""
    global _browser
    driver, _browser = _browser, None
    metrics.set("netflix_browser_warm", 0)
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            logger.warning("Browser cleanup failed")


def get_browser():
    """Keep one browser ready; rebuild it after a failed workflow."""
    global _browser
    if _browser is not None:
        try:
            _browser.window_handles
            return _browser
        except Exception:
            close_browser()
    started = time.monotonic()
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    for argument in ("--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"):
        options.add_argument(argument)
    for attempt in range(2):
        service = Service('/usr/bin/chromedriver')
        try:
            _browser = webdriver.Chrome(options=options, service=service)
            _browser.set_page_load_timeout(30)
            _browser.set_script_timeout(30)
            break
        except Exception as exception:
            service.stop()
            close_browser()
            if attempt or not isinstance(exception, WebDriverException):
                metrics.set("netflix_selenium_available", 0)
                metrics.increment("netflix_selenium_start_failure_total")
                raise
            logger.warning("Browser startup failed; retrying once")
            time.sleep(2)
    metrics.update(
        netflix_browser_warm=1,
        netflix_browser_start_duration_seconds=time.monotonic() - started,
        netflix_selenium_available=1,
        netflix_selenium_last_start_timestamp_seconds=time.time(),
    )
    metrics.increment("netflix_selenium_start_success_total")
    return _browser


def open_link_with_selenium(body):
    """Opens Selenium, logins to Netflix and clicks a button to confirm connection"""
    started = time.monotonic()
    if not body:
        logger.warning("Email body is empty; skipping Selenium flow")
        metrics.workflow_finished(False, time.monotonic() - started)
        return "Empty email body", None

    links = extract_links(body)
    for link in links:
        if "update-primary-location" not in link:
            continue

        logger.info("Found update link")
        driver = None
        succeeded = False
        try:
            metrics.set("netflix_workflow_stage", 2)
            driver = get_browser()
            navigated = time.monotonic()
            driver.get(link)
            logger.info("Opened Netflix update link")
            metrics.set("netflix_navigation_duration_seconds", time.monotonic() - navigated)
            metrics.set("netflix_workflow_stage", 3)
            if not login_to_netflix(driver):
                metrics.workflow_finished(False, time.monotonic() - started)
                return "Netflix login failed", driver.page_source

            def check_button_or_message(current_driver):
                try:
                    button = current_driver.find_element(
                        By.XPATH,
                        '//button[@data-uia="set-primary-location-action"]',
                    )
                    if button.is_displayed() and button.is_enabled():
                        return button
                except NoSuchElementException:
                    pass
                try:
                    message = current_driver.find_element(
                        By.XPATH,
                        '//h1[text()="This link is no longer valid"]',
                    )
                    if message.is_displayed():
                        return message
                except NoSuchElementException:
                    pass
                return None

            metrics.set("netflix_workflow_stage", 4)
            try:
                element = WebDriverWait(driver, 5).until(check_button_or_message)
                if "This link is no longer valid" in driver.page_source:
                    metrics.workflow_finished(False, time.monotonic() - started)
                    return "This link is no longer valid", driver.page_source
                element.click()
                WebDriverWait(driver, 10).until(EC.any_of(
                    EC.visibility_of_element_located(
                        (By.XPATH, '//h1[text()="You’ve updated your Netflix Household"]')
                    ),
                    EC.visibility_of_element_located(
                        (By.XPATH, '//h1[text()="This link is no longer valid"]')
                    ),
                ))
                if "This link is no longer valid" in driver.page_source:
                    metrics.workflow_finished(False, time.monotonic() - started)
                    return "This link is no longer valid", driver.page_source
                succeeded = True
                logger.info("Netflix Household update succeeded")
                metrics.workflow_finished(True, time.monotonic() - started)
                return "Success", driver.page_source
            except TimeoutException:
                logger.error("Timeout waiting for Netflix confirmation")
            metrics.workflow_finished(False, time.monotonic() - started)
            return "Timeout waiting for Netflix confirmation", driver.page_source
        except Exception as exception:
            if driver is None:
                metrics.set("netflix_selenium_available", 0)
            logger.error(
                "An error occurred while processing Netflix update",
                extra={"error": str(exception)},
                exc_info=True,
            )
            metrics.workflow_finished(False, time.monotonic() - started)
            page = None
            if driver is not None:
                try:
                    page = driver.page_source
                except Exception:
                    pass
            return f"An error occurred while processing the link: {exception}", page
        finally:
            if succeeded:
                try:
                    driver.get("about:blank")
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
                    open_link_with_selenium(body)
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
                    get_browser()
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
