# Backend image. Build from the repo root:
#   docker build -f backend/Dockerfile -t content-studio-backend .
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, for layer caching
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

# Project files: backend code plus AGENTS.md and skills/, which get copied
# into every sandbox (see .dockerignore for what is left out)
COPY . .

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
