FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY poarta_contabila ./poarta_contabila
COPY catalog ./catalog
COPY fixtures ./fixtures
RUN uv sync --frozen --no-dev

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn poarta_contabila.app:app --host 0.0.0.0 --port ${PORT} --log-config /app/poarta_contabila/log_config.json"]
