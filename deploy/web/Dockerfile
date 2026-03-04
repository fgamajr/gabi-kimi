FROM python:3.13-slim

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY deploy/web/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY web_server.py .
COPY web/ web/

# .env not copied — secrets via Fly env/secrets

EXPOSE 8000

CMD ["python", "web_server.py"]
