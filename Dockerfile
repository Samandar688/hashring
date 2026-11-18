FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached between code changes.
COPY pyproject.toml README.md ./
COPY hashring/__init__.py hashring/__init__.py
COPY node/__init__.py node/__init__.py
COPY gateway/__init__.py gateway/__init__.py
RUN pip install -e .

COPY hashring hashring
COPY node node
COPY gateway gateway
COPY dashboard dashboard
COPY scripts scripts

# Do not run as root.
RUN useradd --create-home app
USER app

EXPOSE 8000

# Default: the whole cluster in one container and one process (fits a free 0.1 CPU / 512 MB host).
# docker-compose.yml overrides this and runs every node in its own container.
# "exec" makes Python PID 1, so it receives SIGTERM and shuts down cleanly.
CMD ["sh", "-c", "exec python scripts/run_single_process.py --host 0.0.0.0 --port ${PORT:-8000}"]
