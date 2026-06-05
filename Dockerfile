FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "email_assistant_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
