# Use the Python:latest image for Linux ARM v7
FROM debian:stable

# Install dependencies
RUN apt-get update && apt-get install -y curl xvfb chromium
COPY pin_nodesource /etc/apt/preferences.d/nodesource

ADD xvfb-chromium /usr/bin/xvfb-chromium
RUN ln -s /usr/bin/xvfb-chromium /usr/bin/google-chrome
RUN ln -s /usr/bin/xvfb-chromium /usr/bin/chromium-browser

# Set environment variable to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install specific version of Chromium
RUN apt-get update \
    && apt-get install -y chromium-chromedriver 

# Install Python and pip
RUN apt-get install -y python3 python3-pip curl unzip libgconf-2-4

# Set working directory
WORKDIR /app

# Copy requirements file and install dependencies
COPY app/requirements.txt .
RUN pip3 install  --break-system-packages -r requirements.txt


# Copy application files
COPY app/ .

# Start Xvfb
# Copy the shell script
COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# Set the entry point to the shell script
ENTRYPOINT ["/usr/local/bin/start.sh"]