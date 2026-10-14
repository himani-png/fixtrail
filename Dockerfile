# FixTrail server image.
#   docker build -t fixtrail .
#   docker run -p 8000:8000 -v fixtrail-data:/data --env-file .env fixtrail
#
# All runtime data (SQLite database, outbox/, uploads/, inbox/) lives in /data,
# so mount a volume there to keep it between restarts and deploys.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/fixtrail.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY skills ./skills
COPY scripts ./scripts

# Run as a non-root user; relative folders (outbox/, uploads/) resolve inside /data.
RUN useradd --create-home --uid 1000 fixtrail && mkdir -p /data && chown fixtrail /data
USER fixtrail
WORKDIR /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# --proxy-headers: trust X-Forwarded-* from the HTTPS proxy in front (e.g. Caddy or a load balancer).
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
