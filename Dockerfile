# b2b outreach sender — runs one production batch of the first email, then stops.
# Contact data and credentials are NOT in the image: mount the server directory
# (/opt/b2b: b2b.sqlite3 + .env) at /app/data. See docs/deployment.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY b2b/ b2b/
COPY config/ config/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/app/data"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["send"]
