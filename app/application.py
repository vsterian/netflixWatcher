"""Module providing confirmation for Netflix Household update"""
import imaplib
import email
import re
import time
import os
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import NoSuchElementException


NETFLIX_LOGIN = "laurentiusabin5@gmail.com"
NETFLIX_PASSWORD = "vodafone@4"
EMAIL_IMAP = "imap.gmail.com"
EMAIL_LOGIN = "vladuttzzz@gmail.com"
EMAIL_PASSWORD = "hlnd mpxz ymwk ijub"
NETFLIX_EMAIL_SENDER = "info@account.netflix.com"



def extract_links(text):
    """Finds all https links"""
    url_pattern = r'https?://\S+'
    urls = re.findall(url_pattern, text)
    return urls


def open_link_with_selenium(body):
    """Opens Selenium, logins to Netflix and clicks a button to confirm connection"""
    print("Opening Selenium WebDriver...")
    links = extract_links(body)
    for link in links:
        if "update-primary-location" in link:
            print("Found update link:", link)
            service = Service()
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            driver = webdriver.Chrome(options=options, service=service)
            try:
                driver.get(link)
                print("Opened link:", link)
                time.sleep(2)  # Ensure page is loaded

                # Check if login fields exist
                try:
                    email_field = driver.find_element('name', 'userLoginId')
                    password_field = driver.find_element('name', 'password')
                except NoSuchElementException:
                    print("Login fields not found. Assuming already logged in.")
                    pass
                    # Proceed to the next part where the code will press the button
                    # (implement this part of the code)

                else:
                    # Log in
                    email_field.send_keys(NETFLIX_LOGIN)
                    print("Filled in Netflix email:", NETFLIX_LOGIN)
                    password_field.send_keys(NETFLIX_PASSWORD)
                    print("Filled in Netflix password")
                    password_field.send_keys(Keys.RETURN)
                    print("Pressed Enter to log in")
                    time.sleep(2)

                def check_button_or_message(driver):
                    try:
                        # Check if the "Set Primary Location" button exists
                        button = driver.find_element(By.CSS_SELECTOR, '[data-uia="set-primary-location-action"]')
                        if button.is_displayed() and button.is_enabled():
                            return button  # Return the element itself if found
                    except NoSuchElementException:
                        pass

                    try:
                        # Check if the message indicating an invalid link exists
                        message = driver.find_element(By.XPATH, '//h1[text()="This link is no longer valid"]')
                        if message.is_displayed():
                            return message  # Return the element itself if found
                    except NoSuchElementException:
                        pass

                    return None  # Return None if neither the button nor the message is found


                retry_count = 3  # Number of times to retry clicking the button
                for _ in range(retry_count):
                    try:
                        element = WebDriverWait(driver, 10).until(check_button_or_message)
                        if element:
                            if "This link is no longer valid" in driver.page_source:
                                print("The link is no longer valid.")
                                return "This link is no longer valid", driver.page_source
                            else:
                                print("Located 'Set Primary Location' button")
                                time.sleep(1)
                                element.click()
                                print("Clicked 'Set Primary Location' button")
                                # Wait for the next screen to load
                                WebDriverWait(driver, 2).until(EC.url_changes(driver.current_url))
                                print("Next screen loaded successfully")
                                break  # Exit the loop as the click was successful
                    except TimeoutException as exception:
                        print("Timeout waiting for 'Set Primary Location' button or invalid link message:", exception)
                        if _ < retry_count - 1:
                            print("Retrying button click...")
                            continue  # Retry clicking the button
                        else:
                            return "Timeout waiting for 'Set Primary Location' button or invalid link message", driver.page_source
            except Exception as e:
                print(f"An error occurred while processing the link: {e}")
                return f"An error occurred while processing the link: {e}", driver.page_source
            finally:
                driver.quit()



def fetch_last_unseen_email():
    """Gets body of last unseen mail from inbox"""
    print("Fetching last unseen email...")
    while True:
        try:
            # Connect to Gmail
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
            mail.select('inbox')
            print("Authenticated with Gmail Account.")

            # Search for unread messages from Netflix
            result, data = mail.search(None, f'(UNSEEN FROM "{NETFLIX_EMAIL_SENDER}")')

            # Process messages
            if result == 'OK':
                message_ids = data[0].split()
                print("Found {} unread messages from Netflix.".format(len(message_ids)))
                for message_id in message_ids:
                    result, message_data = mail.fetch(message_id, '(RFC822)')
                    if result == 'OK':
                        raw_email = message_data[0][1]
                        msg = email.message_from_bytes(raw_email)
                        subject = msg['Subject']
                        print("Subject:", subject)
                        if subject.startswith("Important: How to update your Netflix Household"):
                            print("Email identified as relevant.")
                            body = None
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    body = part.get_payload(decode=True).decode(part.get_content_charset())
                                    print("Extracted email body.")
                                    mail.store(message_id, '+FLAGS', '\Seen')
                                    open_link_with_selenium(body)
                                    break
                            if body:
                                break
            else:
                print("No relevant email found or processed.")
            break

        except imaplib.IMAP4.error as e:
            print(f"IMAP error occurred: {e}")
            time.sleep(20)
            

        except ConnectionResetError as e:
            print(f"ConnectionResetError occurred: {e}")
            time.sleep(20)
            

        finally:
            try:
                # Close connection
                mail.close()
                mail.logout()
            except:
                pass

    



if __name__ == "__main__":
    while True:
        fetch_last_unseen_email()
        time.sleep(10)