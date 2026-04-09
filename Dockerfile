# ── Agentop Backend Image ────────────────────────────────────────────────────
# Multi-stage build: keeps the final image lean.
# Build:  docker build -t agentop/backend:latest .
# Run:    kubectl apply -f k8s/backend/deployment.yaml
#
# What lives IN the image:  Python code, installed packages, Playwright Chromium
# What lives OUTSIDE:       data/ (PVC), .env vars (K8s Secret)
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System packages needed to compile wheels (cryptography, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache friendly)
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install --no-cache-dir ".[dev]" 2>/dev/null || \
    pip install --no-cache-dir .

# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# System packages required by Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Chromium runtime libs
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgtk-3-0 \
    libx11-xcb1 \
    libdbus-1-3 \
    fonts-liberation \
    # Networking tools
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin

# Install Playwright browsers (Chromium only — news scraper uses it)
RUN playwright install chromium

# Copy application source code
# data/ and .env are NOT copied — they come from PVC and K8s Secret
COPY backend/     ./backend/
COPY deerflow/    ./deerflow/
COPY lib/         ./lib/
COPY docs/        ./docs/
COPY mcp-gateway/ ./mcp-gateway/

# Create data directory mount point (PVC will be mounted here)
RUN mkdir -p /app/data /app/output /app/backend/logs /app/backend/memory

# Run as non-root
RUN useradd -m -u 1000 agentop && chown -R agentop:agentop /app
USER agentop

# Backend binds 0.0.0.0 inside the container (env var overrides config.py default)
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000
# Ollama is on the host machine — Docker Desktop resolves host.docker.internal
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
