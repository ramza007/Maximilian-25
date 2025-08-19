# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (build-essential only if you compile wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer cache)
COPY requirements.txt .
# Ensure gunicorn is in requirements; if not, install it explicitly:
RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir gunicorn flask sqlalchemy

# Copy app source
COPY . .

# Create non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Default port for gunicorn
EXPOSE 8000

# Run with gunicorn (adjust "app:app" if your Flask app object is elsewhere)
CMD ["gunicorn", "-b", "0.0.0.0:8000", "app:app", "--workers", "3", "--threads", "2", "--timeout", "60"]
