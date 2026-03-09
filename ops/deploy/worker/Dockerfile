FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN addgroup --system gabi && adduser --system --ingroup gabi --uid 1000 gabi

# Python deps
COPY ops/deploy/worker/requirements-worker.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY src/backend/ src/backend/

# Data directory owned by gabi
RUN mkdir -p /data && chown -R gabi:gabi /data

USER gabi

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8081/health || exit 1

CMD ["python", "-m", "src.backend.worker.main"]
