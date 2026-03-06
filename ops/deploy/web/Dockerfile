FROM python:3.13-slim

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY ops/deploy/web/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY ops/bin/ ops/bin/
COPY src/ src/
COPY src/backend/search/ src/backend/search/
COPY src/backend/ingest/ src/backend/ingest/

# .env not copied — secrets via Fly env/secrets

EXPOSE 8000

CMD ["python", "ops/bin/web_server.py"]
