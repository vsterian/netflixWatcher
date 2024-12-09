# Netflix Household Update Confirmation

## Description
This module provides confirmation for Netflix Household updates by fetching relevant emails from Gmail and processing them to extract necessary information. It utilizes Selenium for web automation to handle confirmation tasks.

## Setup

### Running Locally

1. **Dependencies**: Ensure you have Python installed on your system. Additionally, install the required Python packages using `pip`:
```bash
pip install imaplib email selenium
```
2. **Chrome WebDriver**: Download the Chrome WebDriver compatible with your Chrome browser version and place it in the project directory.
3. **Gmail Credentials** and **Netflix Credentials**: Create a `.env` file in the root of your project with the following format:
```makefile
EMAIL_LOGIN=your_email@gmail.com
EMAIL_PASSWORD=your_email_password
NETFLIX_LOGIN=your_netflix_login
NETFLIX_PASSWORD=your_netflix_password
```
4. Run the script using Python. Ensure you have access to the internet as the script requires web access to interact with Netflix updates.
```bash
python application.py
```

### Running with Docker

There are two ways to run this project with Docker: one using docker and another using docker-compose. From my perspective you should use docker compose one.

1. **Build and Run using Docker**: Use the following command to build and run the container:
```bash
docker build -t netflixwatcher:1.0 .
docker run -d --name netflixwatcher --restart unless-stopped netflixwatcher:1.0
```
2. **Using Docker Compose**: Use the `docker-compose.yml` file in the root of your project with the following content:

Use the following command to run the container:
```bash
docker-compose up -d
```
**Note**: Every time you restart your machine, the container will automatically start back. This setup works on both Windows and Linux machines.

## Workflow

1. The script connects to Gmail every 5 seconds to fetch unread emails.
2. If an unread email from Netflix is found, it extracts the body and processes it to confirm the Netflix Household update.
3. The confirmation process is automated using Selenium.
4. If any errors occur during the process, they are logged in the console.

## Error Handling

* If there's an IMAP error or a `ConnectionResetError` while fetching emails, the script will retry after a delay of 20 seconds.
* All other exceptions are logged in the console.
