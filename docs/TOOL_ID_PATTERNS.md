# Tool ID Pattern Compliance Guide

## Overview

This document describes the tool ID validation patterns required by different LLM providers and how Agentop ensures compliance across all adapters.

## Provider-Specific Patterns

### OpenAI / GitHub Copilot
```regex
^[a-zA-Z0-9_-]{1,64}$
```
- **Allowed characters**: Letters (a-z, A-Z), digits (0-9), underscores (`_`), hyphens (`-`)
- **Maximum length**: 64 characters
- **Error example**: `messages.37.content.1.tool_use.id: String should match pattern '^[a-zA-Z0-9_-]+$'`

### Anthropic (Claude)
```regex
^[a-zA-Z0-9_-]+$
```
- **Allowed characters**: Same as OpenAI
- **No explicit length limit** in docs, but we enforce 64 chars for consistency
- **Applies to**: 
  - `tool_use.id` in message content blocks
  - `tool_result.tool_use_id` in tool result blocks

## The Problem

Tool IDs generated internally may contain characters outside the allowed pattern:
- Dots (`.`) - e.g., `planner.step:1`
- Colons (`:`) - e.g., `agent_call/2`
- Slashes (`/`) - e.g., `model:ollama-qwen`
- Spaces - e.g., `tool call 1`

When these IDs are passed directly to provider APIs, they reject the request with a 400 error.

## The Solution

### 1. Sanitization Layer (`backend/utils/tool_ids.py`)

All tool IDs pass through `sanitize_tool_id()` before being sent to providers:

```python
from backend.utils.tool_ids import sanitize_tool_id

# Invalid ID with dots and colons
clean = sanitize_tool_id("planner.step:1")  # → "planner_step_1"
```

**Transformation rules:**
1. Replace invalid characters with `_`
2. Collapse consecutive underscores
3. Strip leading/trailing underscores
4. Truncate to 64 characters with hash suffix if needed
5. Generate fallback hash if result is empty

### 2. Registry Pattern (`ToolIdRegistry`)

For bidirectional mapping between canonical and sanitized IDs:

```python
from backend.utils.tool_ids import ToolIdRegistry

registry = ToolIdRegistry()
sanitized = registry.register("planner.step:1")  # → "planner_step_1"
canonical = registry.get_canonical("planner_step_1")  # → "planner.step:1"
```

### 3. Adapter Implementation

Each provider adapter must sanitize tool IDs at the boundary:

#### Anthropic Adapter (`backend/gateway/adapters/anthropic.py`)

```python
from backend.utils.tool_ids import sanitize_tool_id

# In _convert_messages():
tc_blocks = [
    {
        "type": "tool_use", 
        "id": sanitize_tool_id(tc["id"]),  # ← Sanitize here
        "name": tc["function"]["name"],
        "input": json.loads(tc["function"].get("arguments", "{}"))
    }
    for tc in m.tool_calls
]
```

#### Streaming Sanitizer (`backend/gateway/streaming.py`)

```python
from backend.utils.tool_ids import sanitize_tool_id

class ToolIdSanitizer:
    def sanitize(self, canonical_id: str) -> str:
        # Ensure Anthropic compatibility
        safe = sanitize_tool_id(f"agp_tc_{uuid.uuid4().hex[:12]}")
        return safe
```

## Prevention Checklist

When adding new provider adapters:

- [ ] Import `sanitize_tool_id` from `backend.utils.tool_ids`
- [ ] Sanitize `tool_use.id` in outgoing message content blocks
- [ ] Sanitize `tool_result.tool_use_id` in tool result blocks
- [ ] Sanitize tool names in tool definitions if the provider requires it
- [ ] Add unit tests with invalid characters (`.`, `:`, `/`, spaces)
- [ ] Verify with provider's API validation rules

## Testing

Run the tool ID tests:

```bash
cd /root/studio/testing/Agentop
.venv/bin/pytest backend/tests/test_tool_ids.py -v
```

Add Anthropic-specific test cases:

```python
def test_anthropic_tool_id_sanitization():
    """Tool IDs must match ^[a-zA-Z0-9_-]+$ for Anthropic API."""
    from backend.utils.tool_ids import sanitize_tool_id
    
    # These would fail Anthropic validation without sanitization
    invalid_ids = [
        "planner.step:1",
        "agent_call/2", 
        "model:ollama-qwen",
        "tool call 1",
        "a" * 65,  # Too long
    ]
    
    pattern = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
    
    for raw_id in invalid_ids:
        sanitized = sanitize_tool_id(raw_id)
        assert pattern.match(sanitized), f"{sanitized!r} doesn't match pattern"
```

## Common Errors

### Error: `String should match pattern '^[a-zA-Z0-9_-]+$'`

**Cause**: Tool ID contains invalid characters (dots, colons, slashes, spaces)

**Fix**: Apply `sanitize_tool_id()` before sending to provider API

**Location**: Check the adapter in `backend/gateway/adapters/{provider}.py`

## References

- OpenAI API Docs: https://platform.openai.com/docs/api-reference
- Anthropic API Docs: https://docs.anthropic.com/en/api/messages
- Implementation: `backend/utils/tool_ids.py`
- Tests: `backend/tests/test_tool_ids.py`
