# Use the Python:latest image for Linux ARM v7
FROM --platform=linux/arm/v7 debian:bullseye

# Set environment variable to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Chromium non-interactively
RUN apt-get update 
RUN apt-get install -y chromium 
RUN apt-get install chromium-driver
RUN apt-get install -y  xvfb

# Install Python and pip
RUN apt-get install -y python3 python3-pip

WORKDIR /app

COPY app/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app/ .

CMD ["python3", "application.py"]
