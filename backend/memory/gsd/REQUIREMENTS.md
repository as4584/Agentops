# GSD REQUIREMENTS

> Project intent captured once; referenced by plan-phase and execute-phase.
> Last Updated: 2026-03-07

## Project: Agentop

### Core Mission
Multi-tenant AI agent operations platform. Owners manage customers, assign agent
services (website, SEO, AI receptionist, social media), and monitor live agent
execution — all within a VS Code extension + Next.js dashboard backed by a
FastAPI/LangGraph engine.

### Invariants
- All mutations go through the LangGraph orchestrator or sanctioned route modules — never direct agent ↔ agent calls.
- Drift Guard middleware intercepts every tool call; structural changes require doc update first.
- TDD: every runtime change must have a corresponding test — Gatekeeper blocks ungated mutations.
- Atomic writes only (tmp → rename) for all JSON/Markdown state files.
- No secrets in source; AGENTOP_API_SECRET required in prod.

### Architecture Boundaries
- VS Code extension: orchestration boundary only — delegates 100% to backend.
- Next.js dashboard: read-only by default; mutations via sanctioned REST endpoints.
- FastAPI backend: single source of truth for agent state, tool execution, memory.
- MCP gateway: optional docker CLI bridge; degrades gracefully if absent.

### Technology Stack
- Backend: Python 3.11+, FastAPI, LangGraph, Pydantic v2, SQLite (WAL mode)
- Frontend: Next.js 14, TypeScript, Tailwind CSS, Playwright E2E
- LLM: Ollama (local) + OpenRouter (cloud) via unified_registry.py
- Memory: namespaced JSON files under backend/memory/ + SQLite for structured data
- Tools: 12 native + 26 MCP tools; permission-gated per agent tier
