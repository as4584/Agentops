---
agent: agent
description: "Security Review — OWASP-aligned checklist for FastAPI endpoints, auth, secrets, SQL, file uploads, and rate limiting."
tools: [search/codebase]
---

# Security Review

Run this skill before merging any code that: adds authentication, handles user input, creates new API endpoints, works with secrets, or stores/transmits sensitive data.

## When to Activate

- Implementing authentication or authorization
- Handling user input or file uploads
- Creating new FastAPI routes
- Working with API keys, tokens, or credentials
- Storing or transmitting sensitive data
- Integrating third-party APIs

---

## Checklist

### 1. Secrets Management

**Scan for hardcoded secrets:**
```bash
cd /root/studio/testing/Agentop

# API keys / tokens
grep -rn "sk-\|Bearer \|api_key\s*=\s*['\"]" --include="*.py" backend/ 2>/dev/null | grep -v ".env" | grep -v "os.environ\|os.getenv\|settings\." | head -20

# Hardcoded passwords
grep -rn "password\s*=\s*['\"][^'\"]\+" --include="*.py" backend/ 2>/dev/null | grep -v "test_\|mock_\|example\|placeholder" | head -10
```

**Required pattern:**
```python
# ✅ Always use environment variables
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openai_api_key: str
    database_url: str
    secret_key: str

    class Config:
        env_file = ".env"

settings = Settings()

# ❌ Never hardcode
openai_api_key = "sk-proj-xxxxx"
```

- [ ] No hardcoded API keys, tokens, or passwords in source
- [ ] All secrets loaded from environment / `Settings`
- [ ] `.env` and `.env.local` in `.gitignore`
- [ ] No secrets in git history (`git log -p --all | grep -i "sk-"`)

---

### 2. Input Validation

All user-provided data must be validated before use. Pydantic models are the correct tool in Agentop's FastAPI stack:

```python
from pydantic import BaseModel, field_validator, constr
from fastapi import HTTPException

class GenerateRequest(BaseModel):
    brand_name: constr(min_length=1, max_length=100, strip_whitespace=True)
    domain: constr(min_length=1, max_length=80)
    primary_color: str = "#2563EB"

    @field_validator("primary_color")
    @classmethod
    def validate_hex(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?", v):
            raise ValueError("Invalid hex color")
        return v.upper()

@router.post("/generate")
async def generate(req: GenerateRequest):
    # req is already validated — safe to use
    ...
```

**File uploads:**
```python
from fastapi import UploadFile, HTTPException

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

async def validate_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "File too large (max 5 MB)")
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Unsupported type: {file.content_type}")
    return content
```

- [ ] All route inputs go through Pydantic models
- [ ] File uploads: size, MIME type, extension all checked
- [ ] Error messages don't leak internal stack traces to the client

---

### 3. SQL Injection Prevention

Agentop uses SQLAlchemy. Always use the ORM or parameterized expressions — never build SQL strings manually:

```python
from sqlalchemy import select, text
from backend.database.models import WebgenResult

# ✅ ORM query — safe
stmt = select(WebgenResult).where(WebgenResult.job_id == job_id)
result = await session.execute(stmt)

# ✅ Raw SQL requires bindparams
stmt = text("SELECT * FROM webgen_results WHERE job_id = :jid")
result = await session.execute(stmt, {"jid": job_id})

# ❌ NEVER concatenate user input into SQL
query = f"SELECT * FROM results WHERE job_id = '{job_id}'"  # SQLi vulnerability
```

- [ ] No f-string or %-style SQL construction with user values
- [ ] All raw SQL uses `:named` bind parameters

---

### 4. Authentication & Authorization

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def require_auth(token = Depends(security)) -> dict:
    try:
        payload = verify_jwt(token.credentials)
        return payload
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# ✅ Protected route
@router.get("/admin/jobs")
async def list_jobs(user = Depends(require_auth)):
    ...
```

**Cookie storage (if applicable):**
```python
# ✅ httpOnly cookies — not accessible from JS
response.set_cookie(
    key="session",
    value=token,
    httponly=True,
    secure=True,          # HTTPS only in production
    samesite="strict",
    max_age=3600,
)

# ❌ Never store auth tokens in localStorage (XSS risk)
```

- [ ] All sensitive routes use `Depends(require_auth)` or equivalent
- [ ] JWT verification uses a proper library, not manual decode
- [ ] Tokens use httpOnly cookies where applicable

---

### 5. Rate Limiting

Protect LLM endpoints from abuse. Agentop has `backend/security_middleware.py` — verify it covers:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/generate")
@limiter.limit("10/minute")
async def generate(request: Request, brief: ClientBrief):
    ...
```

- [ ] LLM-calling endpoints are rate-limited
- [ ] Rate limits are applied per IP or per authenticated user

---

### 6. Dependency Security

```bash
# Check for known vulnerabilities
pip-audit 2>&1 | head -30

# Check for outdated packages with known CVEs
safety check 2>&1 | head -30
```

- [ ] No packages flagged by `pip-audit`
- [ ] Dependencies pinned in `requirements.txt`

---

### 7. OWASP Top 10 Quick Scan

| # | Risk | Check |
|---|---|---|
| A01 | Broken Access Control | All admin routes require auth |
| A02 | Cryptographic Failures | Secrets in env, not source |
| A03 | Injection | Parameterized SQL, validated inputs |
| A04 | Insecure Design | No debugging routes exposed in production |
| A05 | Security Misconfiguration | CORS locked down, debug=False in prod |
| A06 | Vulnerable Components | `pip-audit` clean |
| A07 | Auth Failures | JWTs verified, no token in URL params |
| A08 | Data Integrity Failures | No untrusted deserialization |
| A09 | Logging Failures | No secrets logged, errors are logged |
| A10 | SSRF | User-provided URLs fetched only through allow-list |

---

## CORS Check

```python
from fastapi.middleware.cors import CORSMiddleware

# ✅ Explicit allow-list
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://agentop.app", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ❌ Do not use in production
allow_origins=["*"]
```

- [ ] CORS does not use `["*"]` in production config

---

## Final Scan Commands

```bash
cd /root/studio/testing/Agentop

# All potential secret patterns
grep -rEn "(password|secret|token|api_key)\s*=\s*['\"][A-Za-z0-9]" \
  --include="*.py" backend/ | grep -v "test_\|example\|placeholder\|os\."

# Debug routes
grep -rn "debug\s*=\s*True\|DEBUG\s*=\s*True" --include="*.py" backend/ | grep -v "test_"

# Verify CORS settings
grep -rn "allow_origins" --include="*.py" backend/
```
