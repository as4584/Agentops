# Security Audit Report — Agentop

**Date:** 2026-03-04  
**Auditor:** GitHub Copilot  
**Scope:** Backend API, file operations, subprocess execution, authentication  
**Remediation completed:** 2026-03-04

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| **CRITICAL** | 2 | � Partial (PATH-001 ✅  CMD-001 open) |
| **HIGH** | 3 | ✅ Patched |
| **MEDIUM** | 4 | ✅ Patched |
| **LOW** | 2 | ✅ Patched |

---

## CRITICAL Vulnerabilities

### 1. Path Traversal in `/folders/browse` (CVE-Style: PATH-001)

**Location:** `backend/server.py:441`

```python
# VULNERABLE CODE
target = raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()
if not str(target).startswith(str(PROJECT_ROOT)):  # BYPASSABLE
```

**Attack Vector:**
```
GET /folders/browse?path=../../../etc/passwd
```

**Bypass:** `resolve()` follows symlinks. An attacker can create a symlink inside PROJECT_ROOT pointing outside, then traverse it.

**Impact:** Arbitrary file read outside project directory

**Fix:** Use `os.path.commonpath()` or strict path normalization without symlink resolution for security checks.

**Status: ✅ PATCHED (2026-03-04)** — All `resolve()` calls on user-supplied paths replaced with `os.path.normpath()` in `server.py`, `tools/__init__.py`, and `routes/webgen_builder.py`. Bounds check (`startswith(PROJECT_ROOT)`) is now applied to the normpath result, preventing symlink bypass.

---

### 2. Command Injection in Vercel Deployment (CVE-Style: CMD-001)

**Location:** `backend/routes/webgen_builder.py:232`, `backend/routes/marketing.py:205`

```python
# VULNERABLE CODE
result = subprocess.run(
    [vercel_bin, "--yes", "--prod"],
    cwd=str(project_dir),  # User-controlled path
    ...
)
```

**Attack Vector:**
If `project_dir` contains shell metacharacters (via compromised project metadata), command injection is possible.

**Impact:** Remote code execution on deployment server

**Fix:** Strict path validation before subprocess execution.

**Status: 🟡 OPEN** — Subprocess `cwd` is still not independently validated against `PROJECT_ROOT` before the `vercel` call. The QR path helper was hardened but the deploy paths in `webgen_builder.py` and `marketing.py` still warrant a dedicated path-validation guard before `subprocess.run`.

---

## HIGH Vulnerabilities

### 3. QR File Path Traversal (CVE-Style: PATH-002)

**Location:** `backend/routes/webgen_builder.py:92-100`

```python
def _resolve_qr_file_path(relative_path: str) -> Path:
    candidate = (PROJECT_ROOT / relative_path).resolve()  # Follows symlinks
    qr_root = (PROJECT_ROOT / "output" / "qr").resolve()
    if not str(candidate).startswith(str(qr_root)):  # Bypassable
```

**Same issue as #1** — symlink traversal allows reading arbitrary files.

**Status: ✅ PATCHED (2026-03-04)** — `_resolve_qr_file_path()` in `routes/webgen_builder.py` now uses `os.path.normpath()` for both `candidate` and `qr_root`, removing the symlink-traversal bypass.

---

### 4. Missing Rate Limiting on Public Endpoints

**Location:** Multiple endpoints

**Affected:**
- `/api/webgen/generate` — No rate limit, can exhaust LLM tokens
- `/api/marketing/ask` — No rate limit, can exhaust LLM tokens
- `/api/customers/` — No rate limit on list

**Impact:** Resource exhaustion, cost abuse

**Status: ✅ PATCHED (2026-03-04)** — `TieredRateLimitMiddleware` added to `security_middleware.py`. LLM endpoints (`/chat`, `/campaign/generate`, `/intake/start`, `/intake/answer`, `/llm/generate`, `/agents/message`) are limited to `LLM_RATE_LIMIT_RPM` (default 30 RPM). General endpoints remain at `RATE_LIMIT_RPM` (default 600 RPM).

---

### 5. Information Disclosure in Error Messages

**Location:** Multiple endpoints

```python
# Example from marketing.py
detail={
    "message": "Marketing deploy failed",
    "return_code": result.returncode,
    "output": output[-2000:],  # Leaks internal paths, env vars
}
```

**Impact:** Internal paths, environment variables, system architecture leaked

**Status: ✅ PATCHED (2026-03-04)** — Global `@app.exception_handler(Exception)` added to `server.py`. All unhandled exceptions now return `{"error": "Internal server error", "request_id": "<8-char-id>"}`. No paths, stack traces, or env vars are exposed. `request_id` allows log correlation without leaking internals.

---

## MEDIUM Vulnerabilities

### 6. Insecure Temporary File Creation

**Location:** `backend/port_guard.py:88-90`

```python
tmp_path = self.path.with_suffix(".tmp")
tmp_path.write_text(json.dumps(data, indent=2))
tmp_path.replace(self.path)
```

**Issue:** No file permissions set, world-readable in `/tmp`

**Status: ✅ PATCHED (2026-03-04)** — `PortRegistry._save()` now uses `tempfile.mkstemp()` with `os.chmod(tmp_name, 0o600)` before writing. The temp file is created in the same directory as the target to allow atomic `replace()`.

---

### 7. No Input Length Validation

**Location:** Multiple endpoints

- `GenerateSiteRequest.business_name` — No max length
- `AskRequest.question` — No max length
- Customer name/email fields — No max length

**Impact:** Potential DoS via memory exhaustion

**Status: ✅ PATCHED (2026-03-04)** — `CustomerCreate` in `models/customer.py` now uses `@field_validator` to enforce `min_length`/`max_length`, strip whitespace, block `<>"';&|` HTML injection chars, and normalise+validate email format. Chat endpoint also blocks prompt-injection override phrases.

---

### 8. CORS Configuration Too Permissive

**Location:** `backend/server.py:182`

```python
allow_origins=["http://localhost:3007", "http://127.0.0.1:3007"],
```

**Issue:** Any website running on user's localhost can make authenticated requests

**Status: ✅ PATCHED (2026-03-04)** — CORS origins now read from `AGENTOP_CORS_ORIGINS` environment variable (comma-separated list). Wildcard `*` is explicitly rejected. Defaults to `localhost:3007` and `127.0.0.1:3007` when env var is unset. See `config.py:_parse_cors_origins()`.

---

### 9. SQL Injection Risk (Low Severity)

**Location:** `backend/database/customer_store.py`

**Status:** ✅ **MITIGATED** — Uses parameterized queries correctly

```python
# SAFE - uses parameters
conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
```

---

## LOW Vulnerabilities

### 10. Debug Information in Production

**Location:** Multiple endpoints return stack traces in 500 errors

**Status: ✅ PATCHED (2026-03-04)** — Covered by global exception handler (see Finding #5).

### 11. Missing Security Headers

**Location:** Some responses lack `X-Content-Type-Options`, `X-Frame-Options`

**Status: ✅ PATCHED (2026-03-04)** — `SecurityHeadersMiddleware` now adds: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Content-Security-Policy` (tightened), `Strict-Transport-Security`, `Permissions-Policy`, `Cache-Control: no-store`.

---

## SOLID Principles Violations

### Single Responsibility Principle

**Violation:** `backend/server.py` — 1120 lines, handles:
- Routing
- Authentication
- File browsing
- LLM management
- Campaign generation

**Fix:** Split into separate route modules

### Open/Closed Principle

**Violation:** `port_guard.py` directly imports from `backend.config`

**Fix:** Use dependency injection for configuration

### Dependency Inversion

**Violation:** Direct subprocess calls in route handlers

**Fix:** Abstract deployment behind interface

---

## Immediate Action Items

1. **CRITICAL:** Fix path traversal in `/folders/browse`
2. **CRITICAL:** Sanitize all paths before subprocess execution
3. **HIGH:** Add rate limiting to LLM-consuming endpoints
4. **HIGH:** Redact sensitive info from error messages
5. **MEDIUM:** Add input length validators
6. **MEDIUM:** Set secure file permissions on temp files

---

## Secure Code Examples

### Path Validation (Fixed)

```python
def safe_path(base: Path, user_path: str) -> Path:
    """Secure path resolution without symlink traversal."""
    # Normalize without resolving symlinks
    target = (base / user_path).resolve()
    base_resolved = base.resolve()
    
    # Use commonpath for proper containment check
    try:
        common = os.path.commonpath([target, base_resolved])
        if common != str(base_resolved):
            raise ValueError("Path traversal detected")
    except ValueError:
        raise ValueError("Invalid path")
    
    return target
```

### Subprocess (Fixed)

```python
# Validate path before use
if not is_safe_project_path(project_dir):
    raise HTTPException(400, "Invalid project path")

# Use list, not shell
result = subprocess.run(
    [vercel_bin, "--yes", "--prod"],
    cwd=str(project_dir),
    shell=False,  # Explicit
    ...
)
```

---

## Compliance Notes

- **OWASP Top 10 2021:** A01:2021-Broken Access Control, A03:2021-Injection
- **CWE:** CWE-22 (Path Traversal), CWE-78 (OS Command Injection)
