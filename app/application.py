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
from pyvirtualdisplay import Display


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

def login_to_netflix(driver):
    """Handles the login process for Netflix."""
    try:
        # Check if the "Email or Phone number" field is visible
        email_or_phone_field = driver.find_element('name', 'userLoginId')
        if email_or_phone_field.is_displayed():
            # Click on "Use Password" button
            use_password_button = driver.find_element(By.XPATH, '//button[@data-uia="login-toggle-button"]')
            use_password_button.click()
            print("Clicked 'Use Password' button")

            # Use the same username and password
            email_field = driver.find_element('name', 'userLoginId')
            password_field = driver.find_element('name', 'password')
            email_field.send_keys(NETFLIX_LOGIN)
            print("Filled in Netflix email:", NETFLIX_LOGIN)
            password_field.send_keys(NETFLIX_PASSWORD)
            print("Filled in Netflix password")
            password_field.send_keys(Keys.RETURN)
            print("Pressed Enter to log in")
            time.sleep(2)
            return True  # Return True indicating successful login
    except NoSuchElementException:
        pass

    try:
        # Check if the userLoginId and password fields are visible
        email_field = driver.find_element('name', 'userLoginId')
        password_field = driver.find_element('name', 'password')
        if email_field.is_displayed() and password_field.is_displayed():
            email_field.send_keys(NETFLIX_LOGIN)
            print("Filled in Netflix email:", NETFLIX_LOGIN)
            password_field.send_keys(NETFLIX_PASSWORD)
            print("Filled in Netflix password")
            password_field.send_keys(Keys.RETURN)
            print("Pressed Enter to log in")
            time.sleep(2)
            return True  # Return True indicating successful login
    except NoSuchElementException:
        pass

    print("Login fields not found. Assuming already logged in.")
    return False  # Return False indicating that login was not required





def open_link_with_selenium(body):
    """Opens Selenium, logins to Netflix and clicks a button to confirm connection"""
    print("Opening Selenium WebDriver...")
    links = extract_links(body)
    for link in links:
        if "update-primary-location" in link:
            print("Found update link:", link)
            service = Service('/usr/bin/chromedriver') 
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            display = Display(visible=0, size=(1600, 1200))
            display.start()
            driver = webdriver.Chrome(options=options, service=service) 
            
            try:
                driver.get(link)
                print("Opened link:", link)
                time.sleep(2)  # Ensure page is loaded

                # Call login function
                if not login_to_netflix(driver):
                    # If login wasn't required, proceed with other actions
                    continue

                def check_button_or_message(driver):
                    try:
                        # Check if the "Set Primary Location" button exists
                        button = driver.find_element(By.XPATH, '//button[@data-uia="set-primary-location-action"]')
                        if button.is_displayed() and button.is_enabled():
                            print("Located 'Set Primary Location' button")
                            return button  # Return the element itself if found
                    except NoSuchElementException:
                        pass
                    time.sleep(2)
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
                        element = WebDriverWait(driver, 5).until(check_button_or_message)
                        if element:
                            if "This link is no longer valid" in driver.page_source:
                                print("The link is no longer valid.")
                                return "This link is no longer valid", driver.page_source
                            else:
                                
                                element.click()
                                print("Clicked 'Update Button' button")
                                
                                # Wait for the success message element to appear on the next screen
                                try:
                                    WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.XPATH, '//h1[text()="You’ve updated your Netflix Household"]')))
                                    print("Update successful message appeared")
                                    break  # Exit the loop as the update was successful
                                except TimeoutException:
                                    print("Timeout waiting for the update successful message to appear")
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
            #finally:
               # driver.quit()



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
        time.sleep(5)