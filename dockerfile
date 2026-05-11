FROM debian:latest

RUN apt-get update && apt-get install -y curl xvfb chromium chromium-driver

RUN apt-get update && apt-get install -y \
    python3 python3-pip curl unzip

WORKDIR /app

COPY . /app/

RUN pip3 install --break-system-packages -r /app/app/requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python3", "/app/app/application.py"]
