import os
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# OAuth2 credentials
SCOPES = ['https://mail.google.com/']

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_auth_url():
    try:
        # Create flow instance using client ID and client secret
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        
        # Fetch the authorization URL
        auth_url, _ = flow.authorization_url(prompt='consent')

        # Print the URL for the user to visit and authorize
        logging.info(f"Authorization URL: {auth_url}")

        
    except Exception as e:
        logging.error(f"Failed to get authorization URL: {e}")

if __name__ == "__main__":
    get_auth_url()
