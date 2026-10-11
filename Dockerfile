# syntax=docker/dockerfile:1
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
# WITH_OCR=1 adds PaddleOCR + Docling (large; needed for scanned PDFs/images)
ARG WITH_OCR=0
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FINTECH_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install ".$( [ "$WITH_OCR" = "1" ] && echo '[ocr,sentry]' || echo '[sentry]' )"
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=ui /ui/dist ./frontend/dist
RUN useradd -r -u 10001 app && mkdir -p /srv/uploads && chown app /srv/uploads
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')"
# --proxy-headers so rate limiting and logs see the real client IP behind your load balancer
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
