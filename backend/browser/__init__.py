"""Browser Control package for Agentop agent automation.

Provides controlled Playwright-backed browser sessions with:
- Per-agent isolated storage state
- SSRF / URL-scheme allowlisting
- TTL auto-close (default 10 min idle)
- Artifact capture under output/browser/<session_id>/
- Full action auditing via structured logger
"""

from backend.browser.session import BrowserSession
from backend.browser.tooling import BrowserSessionRegistry, get_browser_registry

__all__ = ["BrowserSession", "BrowserSessionRegistry", "get_browser_registry"]
