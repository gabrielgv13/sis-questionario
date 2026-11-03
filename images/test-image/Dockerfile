FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" SEED_PROFILE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && useradd --uid 10001 --create-home app && mkdir /secrets && chown app:app /secrets
COPY images/common/entrypoint.py /app/entrypoint.py
USER 10001:10001
EXPOSE 10000
CMD ["python", "/app/entrypoint.py"]
