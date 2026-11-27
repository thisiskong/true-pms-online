# syntax=docker/dockerfile:1
# tsdb service image. Build from service/tsdb:  docker build -t pms/tsdb:dev .
# Config comes only from environment variables (see .env.example); no .env is baked in.

# --- build: resolve locked dependencies into /app/.venv ----------------------------------------------
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# --- runtime ----------------------------------------------------------------------------------------
FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home tsdb
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Run from the source layout: the stores find their SQL at <src>/../sql (store/*.py: parents[3] / "sql").
COPY src ./src
COPY sql ./sql
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TSDB_WORKERS=2
USER tsdb
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=4 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"]
# Migrations: run the same image with `python -m tsdb.migrate` (compose does this as a one-off service).
CMD ["sh", "-c", "exec uvicorn tsdb.main:app --host 0.0.0.0 --port 8080 --workers \"$TSDB_WORKERS\" --no-access-log"]
