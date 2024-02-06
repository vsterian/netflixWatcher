import imaplib
import email
import re
import time
import os
import logging

# IMAP configuration
EMAIL_IMAP = "imap.gmail.com"
EMAIL_ADDRESS = "vladuttzzz@gmail.com"
EMAIL_PASSWORD = "Magazinonline/!8"
MAILBOX = "inbox"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_last_unseen_email():
    try:
        # Connect to the IMAP server
        mail = imaplib.IMAP4_SSL(EMAIL_IMAP)
        logging.info("Attempting login...")
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        logging.info("Login successful.")
        mail.select(MAILBOX)

        # Search for unseen emails
        result, data = mail.search(None, "UNSEEN")

        # Get the list of email IDs
        email_ids = data[0].split()

        # Fetch the last unseen email
        if email_ids:
            latest_email_id = email_ids[-1]
            result, data = mail.fetch(latest_email_id, "(RFC822)")
            raw_email = data[0][1]

            # Parse the raw email data
            parsed_email = email.message_from_bytes(raw_email)
            
            # Extract necessary information for confirmation
            # Example: Extract subject, sender, and content
            subject = parsed_email["Subject"]
            sender = parsed_email["From"]
            content = parsed_email.get_payload()

            # Perform confirmation based on extracted information
            # Example: Check if subject contains certain keywords
            if "Netflix Household Update" in subject:
                # Perform confirmation actions here
                logging.info("Confirmed Netflix Household Update")

        # Close the mail connection
        mail.close()
        mail.logout()
    except Exception as e:
        logging.error(f"Error: {e}")

if __name__ == "__main__":
    while True:
        fetch_last_unseen_email()
        time.sleep(20)
