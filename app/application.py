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


load_dotenv()
NETFLIX_LOGIN = os.getenv('NETFLIX_LOGIN')
NETFLIX_PASSWORD = os.getenv('NETFLIX_PASSWORD')
EMAIL_IMAP = os.getenv('EMAIL_IMAP')
EMAIL_LOGIN = os.getenv('EMAIL_LOGIN')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
NETFLIX_EMAIL_SENDER = os.getenv('NETFLIX_EMAIL_SENDER')

# Set up logger
logger = setup_logger()



def extract_links(text):
    """Finds all https links"""
    url_pattern = r'https?://\S+'
    urls = re.findall(url_pattern, text)
    return urls

def login_to_netflix(driver):
    """Handles the login process for Netflix."""
    

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
    #print("Opening Selenium WebDriver...")

    

    links = extract_links(body)
    for link in links:
        if "update-primary-location" in link:
            logger.info("Found update link", extra={"link": link})
            service = Service('/usr/bin/chromedriver') #
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            #options.add_argument("--enable-logging=stderr --v=1 &> ~/file.log")
            options.add_argument("--remote-debugging-port=9222")
            os.environ['DISPLAY'] = ':99'
            driver = webdriver.Chrome(options=options, service=service) 
            
            try:
                driver.get(link)
                logger.info("Opened link", extra={"link": link})
                time.sleep(2)  # Ensure page is loaded

                if not login_to_netflix(driver):
                    pass

                def check_button_or_message(driver):
                    try:
                        button = driver.find_element(By.XPATH, '//button[@data-uia="set-primary-location-action"]')
                        if button.is_displayed() and button.is_enabled():
                            logger.info("Located 'Set Primary Location' button")
                            return button  # Return the element itself if found
                    except NoSuchElementException:
                        pass
                    time.sleep(2)
                    try:
                        message = driver.find_element(By.XPATH, '//h1[text()="This link is no longer valid"]')
                        if message.is_displayed():
                            return message  # Return the element itself if found
                            
                    except NoSuchElementException:
                        pass

                    return None 


                retry_count = 3
                for _ in range(retry_count):
                    try:
                        element = WebDriverWait(driver, 5).until(check_button_or_message)
                        if element:
                            if "This link is no longer valid" in driver.page_source:
                                logger.warning("The link is no longer valid")
                                return "This link is no longer valid", driver.page_source
                            else:
                                
                                element.click()
                                logger.info("Clicked 'Update Button' button")
                                
                                try:
                                    WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.XPATH, '//h1[text()="You’ve updated your Netflix Household"]')))
                                    logger.info("Update successful message appeared")
                                    break
                                except TimeoutException:
                                    logger.error("Timeout waiting for the update successful message to appear")
                    except TimeoutException as exception:
                        logger.error("Timeout waiting for 'Set Primary Location' button or invalid link message", 
                                   extra={"exception": str(exception)})

                        if _ < retry_count - 1:
                            logger.info("Retrying button click...")
                            continue  # Retry clicking the button
                        else:
                            return "Timeout waiting for 'Set Primary Location' button or invalid link message", driver.page_source
            except Exception as e:
                logger.error("An error occurred while processing the link", 
                           extra={"error": str(e)}, exc_info=True)
                return f"An error occurred while processing the link: {e}", driver.page_source
            finally:
                driver.quit()



def fetch_last_unseen_email():
    """Gets body of last unseen mail from inbox"""
    #print("Fetching last unseen email...")
    while True:
        try:
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            mail.select('inbox')

            result, data = mail.search(None, f'(UNSEEN FROM "{NETFLIX_EMAIL_SENDER}")')

            if result == 'OK':
                message_ids = data[0].split()
                for message_id in message_ids:
                    result, message_data = mail.fetch(message_id, '(RFC822)')
                    if result == 'OK':
                        raw_email = message_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        subject = msg['Subject']
                        if subject.startswith("Important: How to update your Netflix Household"):
                            logger.info("Email identified as relevant", extra={"subject": subject})
                            body = None
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode(part.get_content_charset())
                                    mail.store(message_id, '+FLAGS', '\\Seen')
                                    open_link_with_selenium(body)
                                    break
                            if body:
                                break
            else:
                logger.info("No relevant email found or processed")
            break

        except imaplib.IMAP4.error as e:
            logger.error("IMAP error occurred", extra={"error": str(e)}, exc_info=True)
            time.sleep(20)
            

        except ConnectionResetError as e:
            logger.error("ConnectionResetError occurred", extra={"error": str(e)}, exc_info=True)
            time.sleep(20)

        except OSError as e:
            logger.error("OSError occurred", extra={"error": str(e)}, exc_info=True)
            time.sleep(20)

        except Exception as e:
            logger.error("An error occurred", extra={"error": str(e)}, exc_info=True)
            time.sleep(20)
            

        finally:
            try:
                mail.close()
                mail.logout()
            except:
                pass

    



if __name__ == "__main__":
    while True:
        fetch_last_unseen_email()
        time.sleep(5)
