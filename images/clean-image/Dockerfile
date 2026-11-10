# syntax=docker/dockerfile:1
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

# Validation has its own environment; development packages never enter runtime.
FROM build AS validation
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-editable
COPY tests ./tests
COPY docs ./docs
COPY images ./images
COPY compose.yaml compose.validation.yaml .env.docker.example .dockerignore ./
RUN useradd --uid 10001 --create-home app
USER 10001:10001
CMD ["python", "/app/images/common/validate.py"]

FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" SEED_PROFILE=0 WEB_HOST=0.0.0.0 PORT=10000 WEB_RELOAD=0
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN useradd --uid 10001 --create-home app && mkdir /secrets && chown app:app /secrets
COPY images/common/entrypoint.py /app/entrypoint.py
USER 10001:10001
EXPOSE 10000
CMD ["python", "/app/entrypoint.py"]
