# Agentop Sandbox — hardened agent execution environment
# Sprint 8 — Docker Sandbox

FROM python:3.12-slim

LABEL org.opencontainers.image.title="agentop-sandbox"
LABEL org.opencontainers.image.description="Hardened sandbox for Agentop agent code execution"

# -------------------------------------------------------------------------
# System packages
# -------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    jq \
    make \
    wget \
    unzip \
    zip \
    build-essential \
    ca-certificates \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------------------
# Non-root agent user
# -------------------------------------------------------------------------
RUN useradd -m -u 1000 -s /bin/bash agent

# -------------------------------------------------------------------------
# Python tooling available inside the container
# -------------------------------------------------------------------------
RUN pip install --no-cache-dir \
    requests \
    httpx \
    pydantic \
    rich

# -------------------------------------------------------------------------
# Workspace directory owned by agent user
# -------------------------------------------------------------------------
RUN mkdir -p /workspace && chown agent:agent /workspace

USER agent
WORKDIR /workspace

# Keep container alive so docker exec works
CMD ["bash", "-c", "while true; do sleep 60; done"]
