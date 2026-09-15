"""Module providing confirmation for Netflix Household update"""
import imaplib
import email
import re
import time
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
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
        # Check if the userLoginId and password fields are visible
        email_field = driver.find_element('name', 'userLoginId')
        password_field = driver.find_element('name', 'password')
        if  password_field.is_displayed(): #email_field.is_displayed() and
            email_field.send_keys(NETFLIX_LOGIN)
            logger.info("Filled in Netflix email", extra={"email": NETFLIX_LOGIN})
            password_field.send_keys(NETFLIX_PASSWORD)
            logger.info("Filled in Netflix password")
            password_field.send_keys(Keys.RETURN)
            logger.info("Pressed Enter to log in")
            time.sleep(2)
            return True  # Return True indicating successful login
    except NoSuchElementException:
        pass
    
    try:
        # Check if the "Email or Phone number" field is visible
        use_password_field = driver.find_element(By.XPATH, '//button[@data-uia="login-toggle-button"]')
        if use_password_field.is_displayed():
            # Click on "Use Password" button
            use_password_button = driver.find_element(By.XPATH, '//button[@data-uia="login-toggle-button"]')
            use_password_button.click()
            logger.info("Clicked 'Use Password' button")
            time.sleep(2)

            # Use the same username and password
            email_field = driver.find_element('name', 'userLoginId')
            password_field = driver.find_element('name', 'password')
            email_field.send_keys(NETFLIX_LOGIN)
            logger.info("Filled in Netflix email", extra={"email": NETFLIX_LOGIN})
            password_field.send_keys(NETFLIX_PASSWORD)
            logger.info("Filled in Netflix password")
            password_field.send_keys(Keys.RETURN)
            logger.info("Pressed Enter to log in")
            time.sleep(2)
            return True  # Return True indicating successful login
    except NoSuchElementException:
        pass

    logger.info("Login fields not found. Assuming already logged in.")
    return True  # Return False indicating that login was not required


    


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
        try:
            metrics.set("netflix_workflow_stage", 2)
            service = Service('/usr/bin/chromedriver')
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--remote-debugging-port=9222")
            os.environ['DISPLAY'] = ':99'
            driver = webdriver.Chrome(options=options, service=service)
            metrics.update(
                netflix_selenium_available=1,
                netflix_selenium_last_start_timestamp_seconds=time.time(),
            )
            metrics.increment("netflix_selenium_start_success_total")

            driver.get(link)
            logger.info("Opened Netflix update link")
            time.sleep(2)
            metrics.set("netflix_workflow_stage", 3)
            if not login_to_netflix(driver):
                raise RuntimeError("Netflix login failed")

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
            for attempt in range(3):
                try:
                    element = WebDriverWait(driver, 5).until(check_button_or_message)
                    if "This link is no longer valid" in driver.page_source:
                        metrics.workflow_finished(False, time.monotonic() - started)
                        return "This link is no longer valid", driver.page_source
                    element.click()
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located(
                            (By.XPATH, '//h1[text()="You’ve updated your Netflix Household"]')
                        )
                    )
                    logger.info("Netflix Household update succeeded")
                    metrics.workflow_finished(True, time.monotonic() - started)
                    return "Success", driver.page_source
                except TimeoutException as exception:
                    logger.error(
                        "Timeout waiting for Netflix confirmation",
                        extra={"exception": str(exception), "attempt": attempt + 1},
                    )
            metrics.workflow_finished(False, time.monotonic() - started)
            return "Timeout waiting for Netflix confirmation", driver.page_source
        except Exception as exception:
            if driver is None:
                metrics.update(
                    netflix_selenium_available=0,
                    netflix_selenium_last_start_timestamp_seconds=time.time(),
                )
                metrics.increment("netflix_selenium_start_failure_total")
            logger.error(
                "An error occurred while processing Netflix update",
                extra={"error": str(exception)},
                exc_info=True,
            )
            metrics.workflow_finished(False, time.monotonic() - started)
            return f"An error occurred while processing the link: {exception}", (
                driver.page_source if driver else None
            )
        finally:
            if driver is not None:
                driver.quit()

    metrics.workflow_finished(False, time.monotonic() - started)
    return "Netflix update link not found", None



def fetch_last_unseen_email():
    """Gets body of last unseen mail from inbox"""
    started = time.monotonic()
    missing_vars = get_missing_env_vars()
    if missing_vars:
        logger.error("Missing required environment variables", extra={"missing": missing_vars})
        metrics.poll_failure(time.monotonic() - started)
        time.sleep(20)
        return

    while True:
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(EMAIL_IMAP)
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            mail.select('inbox')

            result, data = mail.search(None, f'(UNSEEN FROM "{NETFLIX_EMAIL_SENDER}")')

            if result == 'OK':
                message_ids = data[0].split()
                metrics.poll_success(0, time.monotonic() - started)
                for message_id in message_ids:
                    result, message_data = mail.fetch(message_id, '(RFC822)')
                    if result == 'OK':
                        raw_email = message_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        subject = msg.get('Subject', '')
                        if subject.startswith("Important: How to update your Netflix Household"):
                            logger.info("Email identified as relevant")
                            metrics.increment("netflix_matching_emails_total")
                            metrics.set("netflix_matching_emails_pending", 1)
                            body = None
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    payload = part.get_payload(decode=True)
                                    charset = part.get_content_charset() or 'utf-8'
                                    if payload is not None:
                                        body = payload.decode(charset, errors='replace')
                                    mail.store(message_id, '+FLAGS', '\\Seen')
                                    open_link_with_selenium(body)
                                    metrics.set("netflix_matching_emails_pending", 0)
                                    break
                            if body:
                                break
            else:
                metrics.poll_failure(time.monotonic() - started)
                logger.error("IMAP search failed")
            break

        except imaplib.IMAP4.error as e:
            logger.error("IMAP error occurred", extra={"error": str(e)}, exc_info=True)
            metrics.poll_failure(time.monotonic() - started)
            time.sleep(20)
            

        except ConnectionResetError as e:
            logger.error("ConnectionResetError occurred", extra={"error": str(e)}, exc_info=True)
            metrics.poll_failure(time.monotonic() - started)
            time.sleep(20)

        except OSError as e:
            logger.error("OSError occurred", extra={"error": str(e)}, exc_info=True)
            metrics.poll_failure(time.monotonic() - started)
            time.sleep(20)

        except Exception as e:
            logger.error("An error occurred", extra={"error": str(e)}, exc_info=True)
            metrics.poll_failure(time.monotonic() - started)
            time.sleep(20)
            

        finally:
            try:
                mail.close()
                mail.logout()
            except:
                pass

    



if __name__ == "__main__":
    metrics.update(service_up=1)
    try:
        while True:
            fetch_last_unseen_email()
            time.sleep(5)
    finally:
        metrics.set("service_up", 0)
