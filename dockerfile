FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
WORKDIR /app
COPY app/requirements.txt /app/app/requirements.txt
RUN pip install --no-cache-dir -r /app/app/requirements.txt && \
    python -m playwright install --with-deps --no-shell chromium
COPY . /app/
CMD ["python3", "/app/app/application.py"]
