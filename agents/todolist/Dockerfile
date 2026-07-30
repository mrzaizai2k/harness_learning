FROM python:3.11-slim

WORKDIR /app

# Install uv (copied from the official distroless uv image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy requirements first (better layer caching)
COPY requirements.txt ./

# Install dependencies with uv (system Python, no venv needed in container)
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code
COPY *.py ./

CMD ["python", "main.py"]