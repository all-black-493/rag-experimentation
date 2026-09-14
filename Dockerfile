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

# Bake the model weights into the image. Downloading them on first use instead
# would make the first query after a deploy wait on a ~100MB fetch, and would
# leave the container needing outbound access to HuggingFace to serve at all.
# Its own layer, before the app code, so editing app/ doesn't refetch them.
ENV HF_HOME=/opt/models \
    TRANSFORMERS_OFFLINE=0
RUN --mount=type=cache,target=/root/.cache/uv \
    python -c "\
from sentence_transformers import CrossEncoder, SentenceTransformer; \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); \
SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY app ./app
COPY frontend ./frontend
COPY prompts ./prompts
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["fastapi", "run", "app/main.py", "--port", "8000", "--host", "0.0.0.0"]
