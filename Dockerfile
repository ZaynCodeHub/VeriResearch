# Backend API image. Builds the veriresearch package with the extras the
# deployed API needs: api + db always, plus llm + search since this
# deployment runs in live mode (GROK_API_KEY / TAVILY_API_KEY set) — openai
# and tavily-python are lazily imported by the code only when those keys are
# set, but they still need to be installed at build time here.
FROM python:3.12-slim AS base

WORKDIR /app

# libpq is needed at runtime by psycopg (even the `binary` wheel dynamically
# loads libpq's SSL/locale bits on some base images) — cheap to include.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[api,db,llm,search]"

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Railway injects $PORT; default to 8000 for `docker run` outside Railway.
CMD ["sh", "-c", "uvicorn veriresearch.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

