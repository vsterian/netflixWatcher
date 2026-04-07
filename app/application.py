"""Module providing confirmation for Netflix Household update"""
import imaplib
import email
import re
import time
import os
from dotenv import load_dotenv  # pylint: disable=import-error
from selenium import webdriver  # pylint: disable=import-error
from selenium.webdriver import Keys  # pylint: disable=import-error
from selenium.webdriver.common.by import By  # pylint: disable=import-error
from selenium.webdriver.support.ui import WebDriverWait  # pylint: disable=import-error
from selenium.webdriver.support import expected_conditions as EC  # pylint: disable=import-error
from selenium.common.exceptions import TimeoutException  # pylint: disable=import-error
from selenium.webdriver.chrome.service import Service  # pylint: disable=import-error
from selenium.common.exceptions import NoSuchElementException  # pylint: disable=import-error
from logger import setup_logger


load_dotenv()
NETFLIX_LOGIN = os.getenv('NETFLIX_LOGIN')
NETFLIX_PASSWORD = os.getenv('NETFLIX_PASSWORD')
EMAIL_IMAP = os.getenv('EMAIL_IMAP')
EMAIL_LOGIN = os.getenv('EMAIL_LOGIN')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
NETFLIX_EMAIL_SENDER = os.getenv('NETFLIX_EMAIL_SENDER')

logger = setup_logger()


def extract_links(text):
    """Finds all https links in text."""
    url_pattern = r'https?://\S+'
    return re.findall(url_pattern, text)


def _fill_credentials(driver):
    """Fill email and password fields and submit the login form."""
    email_field = driver.find_element(By.NAME, 'userLoginId')
    password_field = driver.find_element(By.NAME, 'password')
    email_field.send_keys(NETFLIX_LOGIN)
    logger.info("Filled in Netflix email", extra={"email": NETFLIX_LOGIN})
    password_field.send_keys(NETFLIX_PASSWORD)
    logger.info("Filled in Netflix password")
    password_field.send_keys(Keys.RETURN)
    logger.info("Pressed Enter to log in")
    time.sleep(2)


def login_to_netflix(driver):
    """Handles the login process for Netflix."""
    try:
        password_field = driver.find_element(By.NAME, 'password')
        if password_field.is_displayed():
            _fill_credentials(driver)
            return True
    except NoSuchElementException:
        pass

    try:
        toggle_btn = driver.find_element(
            By.XPATH, '//button[@data-uia="login-toggle-button"]'
        )
        if toggle_btn.is_displayed():
            toggle_btn.click()
            logger.info("Clicked 'Use Password' button")
            time.sleep(2)
            _fill_credentials(driver)
            return True
    except NoSuchElementException:
        pass

    logger.info("Login fields not found. Assuming already logged in.")
    return True


def _check_button_or_message(driver):
    """Return the confirmation button or the invalid-link message element."""
    try:
        button = driver.find_element(
            By.XPATH, '//button[@data-uia="set-primary-location-action"]'
        )
        if button.is_displayed() and button.is_enabled():
            logger.info("Located 'Set Primary Location' button")
            return button
    except NoSuchElementException:
        pass
    time.sleep(2)
    try:
        message = driver.find_element(
            By.XPATH, '//h1[text()="This link is no longer valid"]'
        )
        if message.is_displayed():
            return message
    except NoSuchElementException:
        pass
    return None


def _click_update_button(driver, element, retry_count, attempt):
    """Click the update button and wait for the success message.

    Returns a result tuple if the loop should end, or None to continue retrying.
    """
    if "This link is no longer valid" in driver.page_source:
        logger.warning("The link is no longer valid")
        return "This link is no longer valid", driver.page_source

    element.click()
    logger.info("Clicked 'Update Button' button")
    success_xpath = '//h1[text()="\u2019ve updated your Netflix Household"]'
    try:
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH, success_xpath))
        )
        logger.info("Update successful message appeared")
        return "success", None
    except TimeoutException:
        logger.error("Timeout waiting for the update successful message to appear")
        if attempt < retry_count - 1:
            logger.info("Retrying button click...")
            return None
        return (
            "Timeout waiting for 'Set Primary Location' button or invalid link message",
            driver.page_source,
        )


def _process_link(driver, link):
    """Drive the update-primary-location flow for a single link."""
    driver.get(link)
    logger.info("Opened link", extra={"link": link})
    time.sleep(2)

    login_to_netflix(driver)

    retry_count = 3
    for attempt in range(retry_count):
        try:
            element = WebDriverWait(driver, 5).until(_check_button_or_message)
            if element:
                result = _click_update_button(driver, element, retry_count, attempt)
                if result is not None:
                    return result
        except TimeoutException as exc:
            logger.error(
                "Timeout waiting for 'Set Primary Location' button or invalid link message",
                extra={"exception": str(exc)},
            )
            if attempt < retry_count - 1:
                logger.info("Retrying button click...")
            else:
                return (
                    "Timeout waiting for 'Set Primary Location' button"
                    " or invalid link message",
                    driver.page_source,
                )
    return None


def open_link_with_selenium(body):
    """Open Selenium, log in to Netflix, and click the button to confirm connection."""
    links = extract_links(body)
    for link in links:
        if "update-primary-location" not in link:
            continue
        logger.info("Found update link", extra={"link": link})
        service = Service('/usr/bin/chromedriver')
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--remote-debugging-port=9222")
        os.environ['DISPLAY'] = ':99'
        driver = webdriver.Chrome(options=options, service=service)
        try:
            return _process_link(driver, link)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "An error occurred while processing the link",
                extra={"error": str(exc)},
                exc_info=True,
            )
            return (
                f"An error occurred while processing the link: {exc}",
                driver.page_source,
            )
        finally:
            driver.quit()
    return None


def _process_email_message(mail, message_id, msg):
    """Process a single email message and trigger the Selenium flow if relevant."""
    subject = msg['Subject']
    if not subject.startswith("Important: How to update your Netflix Household"):
        return False
    logger.info("Email identified as relevant", extra={"subject": subject})
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            body = part.get_payload(decode=True).decode(part.get_content_charset())
            mail.store(message_id, '+FLAGS', '\\Seen')
            open_link_with_selenium(body)
            return True
    return False


def _search_and_process_emails(mail):
    """Search inbox for unread Netflix emails and process the first match."""
    result, data = mail.search(None, f'(UNSEEN FROM "{NETFLIX_EMAIL_SENDER}")')
    if result != 'OK':
        logger.info("No relevant email found or processed")
        return
    message_ids = data[0].split()
    for message_id in message_ids:
        fetch_result, message_data = mail.fetch(message_id, '(RFC822)')
        if fetch_result == 'OK':
            raw_email = message_data[0][1]
            msg = email.message_from_bytes(raw_email)
            if _process_email_message(mail, message_id, msg):
                break


def fetch_last_unseen_email():
    """Gets body of last unseen mail from inbox and processes it."""
    while True:
        mail = None
        try:
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            mail.select('inbox')
            _search_and_process_emails(mail)
            break

        except imaplib.IMAP4.error as exc:
            logger.error("IMAP error occurred", extra={"error": str(exc)}, exc_info=True)
            time.sleep(20)

        except ConnectionResetError as exc:
            logger.error(
                "ConnectionResetError occurred", extra={"error": str(exc)}, exc_info=True
            )
            time.sleep(20)

        except OSError as exc:
            logger.error("OSError occurred", extra={"error": str(exc)}, exc_info=True)
            time.sleep(20)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("An error occurred", extra={"error": str(exc)}, exc_info=True)
            time.sleep(20)

        finally:
            if mail is not None:
                try:
                    mail.close()
                    mail.logout()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass


if __name__ == "__main__":
    while True:
        fetch_last_unseen_email()
        time.sleep(5)
