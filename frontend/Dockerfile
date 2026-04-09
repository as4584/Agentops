# ── Agentop Frontend ─────────────────────────────────────────────────────────
# Multi-stage build: install deps → build → serve with minimal runtime image.
# Build:  docker build -t agentop/frontend:latest -f frontend/Dockerfile frontend/
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependencies ────────────────────────────────────────────────────
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts

# ── Stage 2: build ───────────────────────────────────────────────────────────
FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Server-side env vars are baked at build time for Next.js
# AGENTOP_API_URL tells the proxy route where the backend lives inside compose
ARG AGENTOP_API_URL=http://backend:8000
ENV AGENTOP_API_URL=${AGENTOP_API_URL}
ENV DOCKER_BUILD=true

RUN npm run build

# ── Stage 3: runtime ─────────────────────────────────────────────────────────
FROM node:22-slim AS runtime
WORKDIR /app

RUN adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs

ENV PORT=3007
ENV HOSTNAME=0.0.0.0
EXPOSE 3007

# AGENTOP_API_SECRET is injected at runtime via env var (docker-compose / k8s secret)
# — never baked into the image.
CMD ["node", "server.js"]
