SpendTracker – Component Specification  
(only the SpendTracker, nothing else)

----------------------------------------
1. Python interface
----------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Protocol

class SpendInfo(TypedDict):
    model: str
    prompt_tokens: int
    completion_tokens: int
    usd: float


class SpendTracker(Protocol):
    """Runtime singleton that lives inside one build phase."""

    def add_spend(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        """
        Convert token counts → USD via OpenRouter public cost map and
        accumulate. Idempotent: same call twice adds twice.
        Raises OverLimitError if the new total would exceed $1.00.
        Persists the updated state to phase_state.json before returning.
        """

    def get_total(self) -> float:
        """Return current cumulative USD spend for this build."""

    def is_over_limit(self) -> bool:
        """Return True only if total > $1.00."""


@dataclass(slots=True)
class OverLimitError(RuntimeError):
    total: float


# Internal persistent shape (written to phase_state.json)
@dataclass
class _State:
    total_usd: float
    model_counter: Dict[str, int]  # how many calls per model (diagnostic only)

----------------------------------------
2. Core logic (step-by-step)
----------------------------------------
1. Constructor  
   a. Load phase_state.json from cwd; if missing treat as {"total_usd": 0.0, "model_counter": {}}  
   b. Build in-memory lookup dict:  
      openrouter_prices = {  
        "openai/gpt-4": {"in": 0.03, "out": 0.06},  
        "openai/gpt-3.5-turbo": {"in": 0.001, "out": 0.002},  
        "anthropic/claude-3-haiku": {"in": 0.00025, "out": 0.00125},  
        … 20 biggest models …  
      }  
   c. Keep _state in memory.

2. add_spend(model, prompt_tokens, completion_tokens)  
   a. Lookup model in openrouter_prices → raise UnknownModelError if absent.  
   b. cost = prompt_tokens * price.in/1000 + completion_tokens * price.out/1000  
   c. If _state.total_usd + cost > 1.00 → raise OverLimitError(_state.total_usd + cost)  
   d. Else:  
         _state.total_usd += cost  
         _state.model_counter[model] = _state.model_counter.get(model,0) + 1  
         atomically write _state to phase_state.json (write to tmp file, then rename).  
   e. Return None.

3. get_total() → float(_state.total_usd)  
4. is_over_limit() → _state.total_usd > 1.00  

----------------------------------------
3. Edge cases handled
----------------------------------------
- File not present on first run → treat as zero state  
- phase_state.json corrupted / not JSON → raise ValueError, do not start  
- Concurrent add_spend calls (asyncio or threads) → atomic file write + rename prevents torn files (but in-memory race still possible; caller must serialise or accept last-write-wins)  
- Unknown model string → UnknownModelError (subclass of ValueError)  
- Zero or negative token counts → accepted (cost = 0)  
- Over-limit detected mid-call → exception before persistence, so state never exceeds 1.00  
- External manual edit of phase_state.json that pushes total above 1.00 → is_over_limit() immediately returns True, but add_spend will still reject any *new* cost that would increase it further  
- Resetting a build → caller deletes phase_state.json; tracker starts fresh  

----------------------------------------
4. What it should NOT do
----------------------------------------
- No global rate-limiting, per-minute budgets, or credit refill  
- No network calls to OpenRouter for live prices; use hard-coded table  
- No timezone tracking, timestamps, or historical roll-up  
- No alerting, Slack hooks, or e-mails  
- No interaction with any other dashboard component (optimizer, router, cache, etc.)  
- No automatic build abortion; only raises exception on add_spend, caller decides next step