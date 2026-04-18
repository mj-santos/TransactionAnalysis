FROM python:3.12-slim

WORKDIR /app

# System deps kept minimal for deterministic local builds
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir -U pip setuptools wheel \
    && pip install --no-cache-dir .

# runtime data mounts (db, reports, parquet, raw)
VOLUME ["/app/data"]

CMD ["finance_etl", "--help"]
