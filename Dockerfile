FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies in their own layer so app-code edits don't invalidate it.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app
COPY frontend ./frontend
COPY prompts ./prompts
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--host", "0.0.0.0"]
