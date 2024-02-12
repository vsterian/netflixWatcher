# Use the Python:latest image for Linux ARM v7
FROM --platform=linux/arm/v7 debian:bullseye

# Set environment variable to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install specific version of Chromium
RUN apt-get update \
    && apt-get install -y chromium=120.0.6099.102 \
    && apt-get install -y chromium-driver \
    && apt-get install -y xvfb

# Install Python and pip
RUN apt-get install -y python3 python3-pip

# Set working directory
WORKDIR /app

# Copy requirements file and install dependencies
COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ .

# Start Xvfb and run the Python script
CMD Xvfb :99 -screen 0 1600x1200x16 & \
    sleep 3 && \
    python3 application.py
