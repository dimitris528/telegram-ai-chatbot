FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/app/data/conversations.db

WORKDIR /app

# Dependencies first, so code changes don't invalidate the cached layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot ./bot

# Run as an unprivileged user; /app/data holds the SQLite conversation store.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data
USER appuser
VOLUME ["/app/data"]

CMD ["python", "-m", "bot"]
