FROM debian:latest

RUN apt-get update && apt-get install -y curl xvfb chromium chromium-driver
COPY pin_nodesource /etc/apt/preferences.d/nodesource

ADD xvfb-chromium /usr/bin/xvfb-chromium
RUN ln -s /usr/bin/xvfb-chromium /usr/bin/google-chrome
RUN ln -s /usr/bin/xvfb-chromium /usr/bin/chromium-browser

RUN apt-get update && apt-get install -y \
    python3 python3-pip curl unzip libgconf-2-4

WORKDIR /app

COPY . /app/

RUN pip3 install --break-system-packages -r /app/requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python3", "/app/application.py"]
