# Agent Web Browsing — Security Audit & Protection

> Audit date: 2026-04-05
> Auditor: Opus (Claude) automated security review
> Scope: `backend/browser/session.py`, `backend/config.py` SSRF controls

---

## Security Controls — Current State

### 1. SSRF Protection ✅ PASS
- **URL scheme validation**: Only `http://` and `https://` allowed (regex: `^https?://`)
- **Private network blocklist** (13 prefixes):
  - `http://169.254.*` — Cloud metadata (AWS/GCP/Azure)
  - `http://127.*`, `http://localhost` — Loopback
  - `http://[::1]` — IPv6 loopback
  - `http://0.0.0.0` — Wildcard bind
  - `http://10.*`, `http://172.16.*`, `http://192.168.*` — RFC-1918 private
  - All HTTPS variants of the above
- **Validation point**: Before any Playwright network call (call-site, not middleware)
- **Verdict**: Blocks standard SSRF vectors. See recommendations for edge cases.

### 2. Secret Redaction ✅ PASS
- Pattern: `(?i)(password|token|key|secret|auth)`
- Applied to: `type_text()` log entries when selector matches
- Sensitive fields show `[REDACTED]` in logs
- **Verdict**: Adequate for common field names. Consider expanding pattern.

### 3. Session Isolation ✅ PASS
- Each agent gets its own `BrowserSession` instance
- Each session creates a unique `BrowserContext` (Playwright isolation)
- Separate cookie stores, localStorage, sessionStorage per agent
- Screenshots stored in isolated directories: `output/browser/{session_id}/`
- **Verdict**: Strong isolation via Playwright's context model.

### 4. Timeout Controls ✅ PASS
- Navigation timeout: 30s (`NAV_TIMEOUT_MS`)
- Action timeout: 10s (`ACTION_TIMEOUT_MS`)
- Session TTL: 600s (10 min idle eviction)
- Max retries: 2 per action
- **Verdict**: Prevents hung sessions and resource exhaustion.

### 5. Headless Mode ✅ PASS
- Chromium launched in headless mode (`headless=True`)
- No GUI attack surface

---

## Recommendations — Hardening Opportunities

### R1: DNS Rebinding Protection (MEDIUM)
**Risk**: Attacker-controlled DNS resolves to a public IP initially, then rebinds to 127.0.0.1 after validation.
**Fix**: Resolve DNS before validation, then pass the resolved IP to Playwright:
```python
import socket
hostname = urlparse(url).hostname
resolved = socket.getaddrinfo(hostname, None)[0][4][0]
# Check resolved IP against blocklist, not just URL prefix
```

### R2: Redirect Chain SSRF (MEDIUM)
**Risk**: URL passes validation but redirects (302) to a blocked target.
**Fix**: Add `--disable-features=Redirects` or validate the final URL after navigation:
```python
final_url = self._page.url  # after goto()
_validate_url(final_url)  # re-validate
```

### R3: Expand Secret Redaction Patterns (LOW)
Add patterns for: `credit_card`, `ssn`, `cvv`, `pin`, `otp`, `mfa`, `2fa`

### R4: Content Security Policy Headers (LOW)
Inject CSP headers into browser context to prevent XSS in rendered pages:
```python
await self._context.set_extra_http_headers({
    "Content-Security-Policy": "script-src 'none'"
})
```

### R5: Network Proxy for Agent Browsing (RECOMMENDED)
Configure a SOCKS5 proxy (Tor or commercial VPN) to anonymize agent traffic:
```python
self._browser = await self._pw.chromium.launch(
    headless=True,
    proxy={"server": "socks5://127.0.0.1:9050"}  # Tor
)
```
Plus DNS-over-HTTPS to prevent DNS leaks:
```python
# In proxy config
proxy={"server": "socks5://127.0.0.1:9050", "bypass": ""}
# Or at system level: configure systemd-resolved with DoH
```

### R6: User-Agent Rotation (LOW)
Rotate user-agent strings to reduce fingerprinting:
```python
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
]
context = await browser.new_context(user_agent=random.choice(user_agents))
```

---

## Summary

| Control | Status | Severity if Missing |
|---------|--------|-------------------|
| SSRF prefix blocklist | ✅ Implemented | CRITICAL |
| URL scheme validation | ✅ Implemented | CRITICAL |
| Secret redaction | ✅ Implemented | HIGH |
| Session isolation | ✅ Implemented | HIGH |
| Timeout/TTL controls | ✅ Implemented | MEDIUM |
| Headless enforcement | ✅ Implemented | MEDIUM |
| DNS rebinding protection | ⚠️ Not implemented | MEDIUM |
| Redirect chain validation | ⚠️ Not implemented | MEDIUM |
| Network proxy/VPN | ⚠️ Not implemented | MEDIUM |
| User-Agent rotation | ℹ️ Not implemented | LOW |

**Overall Assessment**: The browser automation layer has **solid foundational security**. The SSRF blocklist, session isolation, and secret redaction cover the most common attack vectors. The main gaps are DNS rebinding and redirect-chain SSRF — both medium severity in a local-first environment since the primary threat is untrusted agent instructions, not external attackers.
