
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and Linux dependencies for Playwright.
RUN python -m playwright install --with-deps chromium

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

CMD ["python", "-m", "app.main"]
