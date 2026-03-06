# Agentop AI Gateway

The gateway is a centralized, secure proxy that exposes an **OpenAI-compatible API** (`/v1/*`) over all model providers (local Ollama, OpenRouter, direct OpenAI/Anthropic) with per-API-key authentication, granular ACL, rate limiting, and full audit trails.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Quick Start](#quick-start)
3. [API Reference](#api-reference)
4. [Authentication](#authentication)
5. [Model Access Control](#model-access-control)
6. [Rate Limiting & Quotas](#rate-limiting--quotas)
7. [Provider Secret Vault](#provider-secret-vault)
8. [Audit & Observability](#audit--observability)
9. [Admin API](#admin-api)
10. [Configuration Reference](#configuration-reference)
11. [Security Checklist](#security-checklist)

---

## Architecture

```
Client (agp_sk_* key)
        │
        ▼
┌───────────────────────────────────────────────┐
│  GATEWAY SECURITY PERIMETER                    │
│  • GatewayAuthMiddleware  (HMAC-SHA256)        │
│  • GatewayRateLimitMiddleware (per-key RPM)    │
│  • ModelACL check (whitelist)                  │
│  • RequestValidation (length, safety)          │
└───────────────────┬───────────────────────────┘
                    │
                    ▼
         GatewayRouter (dispatch)
                    │
        ┌───────────┴──────────┐
        ▼           ▼          ▼
   OllamaAdapter  OpenRouterAdapter  OpenAIAdapter / AnthropicAdapter
        │           │          │
        └───────────┴──────────┘
                    │
         Provider circuits + fallback
                    │
                    ▼
        ┌─────────────────────┐
        │  Observability       │
        │  AuditLogger         │
        │  UsageTracker        │
        │  CircuitBreaker      │
        └─────────────────────┘
```

---

## Quick Start

### 1. Set environment variables

```bash
# Required in production
export AGENTOP_GATEWAY_MASTER_KEY="$(openssl rand -hex 32)"
export AGENTOP_ADMIN_SECRET="$(openssl rand -hex 24)"

# Provider keys (or store in vault via admin API)
export OPENROUTER_API_KEY="sk-or-..."
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 2. Create an API key

```bash
curl -X POST http://localhost:8000/admin/keys \
  -H "X-Admin-Secret: $AGENTOP_ADMIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-app",
    "owner": "alice",
    "tier": "standard",
    "quota_daily_usd": 10.0
  }'
```

Response (save `key` — shown once):
```json
{
  "key": "agp_sk_a1b2c3d4_e5f6a7b8c9d0e1f2a3b4c5d6",
  "key_id": "...",
  "message": "Store this key securely — it will not be shown again."
}
```

### 3. Use the gateway (OpenAI-compatible)

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer agp_sk_a1b2c3d4_e5f6a7b8c9d0e1f2a3b4c5d6" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### 4. Use with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="agp_sk_a1b2c3d4_e5f6a7b8c9d0e1f2a3b4c5d6",
    base_url="http://localhost:8000/v1",
)

response = client.chat.completions.create(
    model="llama3.2",
    messages=[{"role": "user", "content": "Tell me a joke"}],
)
print(response.choices[0].message.content)
```

---

## API Reference

### `POST /v1/chat/completions`

OpenAI-compatible chat completion.

**Request body:**
```json
{
  "model": "llama3.2",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2+2?"}
  ],
  "max_tokens": 256,
  "temperature": 0.7,
  "stream": false,
  "tools": [],
  "tool_choice": "auto"
}
```

**Response:** OpenAI `ChatCompletion` schema.

**Streaming:** Set `"stream": true` — returns `text/event-stream` SSE.

---

### `POST /v1/completions`

Legacy text completion. Internally converted to chat.

---

### `GET /v1/models`

Returns models accessible to the authenticated API key.

```json
{
  "object": "list",
  "data": [
    {"id": "llama3.2", "owned_by": "ollama", "context_window": 128000, "supports_tools": false},
    {"id": "gpt-4o", "owned_by": "openai", "context_window": 128000, "supports_tools": true}
  ]
}
```

---

### `GET /v1/health`

Public health endpoint.

---

## Authentication

### Key format
```
agp_sk_{8hex}_{24hex}
```
Example: `agp_sk_a1b2c3d4_e5f6a7b8c9d0e1f2a3b4c5d6`

### Usage
```
Authorization: Bearer agp_sk_...
```

### Security properties
- Keys are hashed (SHA-256) before storage — raw key is **never persisted**
- Timing-safe comparison via `hmac.compare_digest`
- Zero-downtime rotation: primary + secondary key per client
- Automatic expiry support

---

## Model Access Control

Each key starts with **no model access** (default deny). Grant access:

```bash
# Grant a full tier
curl -X PUT http://localhost:8000/admin/keys/{id} \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"add_tier": "standard"}'

# Grant specific models
curl -X PUT http://localhost:8000/admin/keys/{id} \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"add_models": ["llama3.2", "ollama/*", "gpt-4o-mini"]}'
```

### Tiers

| Tier     | Models |
|----------|--------|
| budget   | All Ollama local models |
| standard | kimi-k2, claude-haiku, deepseek, gpt-4o-mini |
| premium  | All cloud models: gpt-4o, claude-sonnet/opus, o1-preview |

### Wildcard patterns

- `ollama/*` — all Ollama models
- `openrouter/kimi-*` — all Kimi variants
- `*` — all models (superuser)

---

## Rate Limiting & Quotas

Per-key limits enforced:
- **RPM** — requests per minute (default: 60)
- **TPM** — tokens per minute (default: 100,000)
- **TPD** — tokens per day (default: 1,000,000)
- **Daily USD** — (default: $5.00)
- **Monthly USD** — (default: $50.00)

Response headers:
```
X-RateLimit-Limit-Requests: 60
X-RateLimit-Remaining-Requests: 57
X-RateLimit-Limit-Tokens: 100000
X-RateLimit-Remaining-Tokens: 99650
```

---

## Provider Secret Vault

Provider API keys are encrypted at rest with AES-256-GCM. Store via admin API:

```bash
curl -X POST http://localhost:8000/admin/secrets \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"provider": "openai", "api_key": "sk-..."}'
```

The vault uses PBKDF2-SHA256 (260,000 iterations) to derive a 256-bit key from `AGENTOP_GATEWAY_MASTER_KEY`. Encrypted file is stored at `backend/memory/gateway_secrets.enc` with `chmod 600`.

**Key rotation:**
```bash
# POST to /admin/secrets will overwrite with new encryption
curl -X POST http://localhost:8000/admin/secrets \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"provider": "openai", "api_key": "sk-new-..."}'
```

---

## Audit & Observability

Structured JSONL audit log at `backend/logs/gateway.jsonl`:

```json
{"ts":"2026-03-04T14:22:01Z","key_id_hash":"a3f8c1b2","model":"llama3.2","provider":"ollama","tokens_in":128,"tokens_out":64,"cost_usd":0.0,"latency_ms":312,"status":200,"stream":false,"error":""}
```

**Privacy protection:** Prompts, completions, and tool call results are **never logged**. Only token counts, costs, and latency are recorded.

Enable debug content logging (development only):
```bash
GATEWAY_DEBUG_LOG_CONTENT=1  # NEVER in production
```

---

## Admin API

All admin endpoints require `X-Admin-Secret: {secret}` or an API key with `admin` scope.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/keys` | Create API key |
| `GET` | `/admin/keys` | List keys |
| `GET` | `/admin/keys/{id}` | Key details + allowed models |
| `PUT` | `/admin/keys/{id}` | Update quotas, ACL, scopes |
| `DELETE` | `/admin/keys/{id}` | Revoke key |
| `GET` | `/admin/keys/{id}/usage` | Usage stats |
| `POST` | `/admin/keys/{id}/rotate` | Generate secondary key |
| `POST` | `/admin/keys/{id}/promote` | Promote secondary to primary |
| `GET` | `/admin/models` | All models with pricing |
| `POST` | `/admin/secrets` | Store provider API key (encrypted) |
| `DELETE` | `/admin/secrets/{provider}` | Remove provider key |
| `GET` | `/admin/audit` | Recent audit log entries |
| `GET` | `/admin/health` | Provider health + circuit status |
| `POST` | `/admin/health/check` | Trigger health check |

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_ENABLED` | `true` | Enable/disable the entire gateway |
| `AGENTOP_GATEWAY_MASTER_KEY` | *(required in prod)* | AES master key for provider secrets |
| `AGENTOP_ADMIN_SECRET` | *(required in prod)* | Admin API authentication secret |
| `GATEWAY_RATE_LIMIT_BACKEND` | `memory` | `memory` or `redis` |
| `GATEWAY_REDIS_URL` | `redis://localhost:6379/0` | Redis URL for distributed rate limiting |
| `GATEWAY_DEFAULT_QUOTA_RPM` | `60` | Default requests/minute per key |
| `GATEWAY_DEFAULT_QUOTA_TPM` | `100000` | Default tokens/minute per key |
| `GATEWAY_DEFAULT_QUOTA_DAILY_USD` | `5.0` | Default daily spend limit |
| `GATEWAY_DEFAULT_QUOTA_MONTHLY_USD` | `50.0` | Default monthly spend limit |
| `GATEWAY_MAX_PROMPT_LENGTH` | `32768` | Max total prompt characters |
| `GATEWAY_MAX_MESSAGES` | `100` | Max messages in a request |
| `GATEWAY_AUDIT_RETENTION_DAYS` | `90` | Log retention |
| `GATEWAY_DEBUG_LOG_CONTENT` | `0` | Log prompt content (dev only!) |
| `GATEWAY_CIRCUIT_BREAKER_THRESHOLD` | `5` | Failures before circuit opens |
| `GATEWAY_CIRCUIT_BREAKER_TIMEOUT` | `60` | Seconds before circuit half-opens |
| `GATEWAY_FALLBACK_ORDER` | `openrouter,openai,anthropic,ollama` | Provider fallback priority |

---

## Security Checklist

- [ ] `AGENTOP_GATEWAY_MASTER_KEY` set to a 32-byte random hex value
- [ ] `AGENTOP_ADMIN_SECRET` set and not exposed in logs
- [ ] `gateway_secrets.enc` has permissions `600` (owner-only)
- [ ] `gateway_keys.db` has permissions `600`
- [ ] `GATEWAY_DEBUG_LOG_CONTENT` is `0` in production
- [ ] Provider keys stored via vault, not plain env vars
- [ ] New API keys start with no model access (explicit grant required)
- [ ] Audit log reviewed regularly for anomalies
- [ ] Daily/monthly spend limits set on all keys
- [ ] Rate limiting enabled (RPM > 0)
- [ ] No provider keys appear in `gateway.jsonl` log
- [ ] Admin secret rotated on personnel changes
