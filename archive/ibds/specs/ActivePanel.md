## ActivePanel – Design & Implementation Spec

### 1. TypeScript interfaces & imports

```ts
// imports
import React, { useEffect, useRef, useState } from 'react';
import { Stack, Group, Text, Badge, Button, ScrollArea, Box } from '@mantine/core';
import { IconRefresh, IconPlayerPlay, IconPlayerStop } from '@tabler/icons-react';

// external types
interface SystemStatus {
  connected: boolean;          // true = green dot
  llm: 'healthy' | 'degraded' | 'error';
  uptime: string;             // "1h 15m"
  drift: 'sync' | 'ahead' | 'behind';
}

interface Agent {
  id: string;
  role: string;
  status: 'online' | 'idle' | 'error';
  lastActive: string;         // ISO
}

interface StreamEvent {
  timestamp: string;          // ISO
  type: string;               // e.g. "agent_ready"
  agentId: string | null;
  detail: string;
}
```

### 2. Component structure (sections & layout)

Layout root is a vertical flex stack, gap 12.  
Panel padding 12px (outer `Box p={12}`).

Header (fixed 36px):  
- Label “ACTIVE” (13/700/Inter uppercase letter-spacing .5px)  
- 8px `.` dot container → green/red circle (`w={6} h={6} radius="50%"`) based on `system.connected`  
- Spacer → refresh icon-only Button 24×24

Section A (Health bar, ~36px):  
Group (nowrap) –  
- Badge for `system.llm` (green/degraded/red variant)  
- Monospace `system.uptime`  
- Text `Active: ${a.length} / ${t.length}`  
- Badge for `system.drift` (`sync` green, ahead/behind orange/red)

Section B (Agent roster):  
ScrollArea (flex 0 1 auto, max-height calc(100% - other sections))  
- `data` sorted: online first, idle, error.  
- Columns:  
  - 12px status dot (color)  
  - `agent_id` (mono)  
  - role truncated (max-w 200)  
  - relative last_active (e.g., “2m ago”)  
  - 24px start/stop icon buttons (play green, stop red) – row-hover visible only  
Scroll border radius 6px.

Section C (SSE stream):  
ScrollArea (flex 1 1 0)  
- max 50 items – tail 50 of array.  
- Date.now()-timestamp (text-xs mono)  
- Badge cyan for event.type  
- agentId (mono) truncated  
- detail truncated (max-w 400)  
- Auto-scroll on new event.  
- Items animate `opacity 0 → 1` 150ms ease-out.

Internal state  
```
const [status, setStatus] = useState<SystemStatus | null>(null);
const [agents, setAgents] = useState<Agent[]>([]);
const [events, setEvents] = useState<StreamEvent[]>([]);
const [initialLoading, setInitialLoading] = useState(true);
const [lastPoll, setLastPoll] = useState<number>(0);
const eventScrollRef = useRef<HTMLDivElement>(null);
```

### 3. Data fetching

Poll GET `/system/status` and GET `/agents` every 5s (`setInterval`).  
AbortController attached to cleanup.  
Stop when `document.hidden` (visibilitychange).  
Re-start when visible again.

SSE `/events/stream`.  
`const sse = new EventSource('/events/stream')`  
Parse newline-delimited JSON -> `StreamEvent`.  
Buffer newest 50 to `events` state.  
Close connection on unmount.

Loading: show skeleton texts in first fetch only. Subsequent updates merge smoothly.  
Error: red text banner under Section A for fetch failures; clickable Retry replaces poll on next attempt.

### 4. Edge cases it must handle

- Tab inactive – polling & SSE both suspended; resume on visibility change.  
- SSE reconnect when network error (auto-retry w/ exponential backing-off).  
- Render overflow agent_id or role – truncate with CSS ellipsis.  
- Endpoint 5xx → show bold red banner; keep last valid state.  
- Agent with null role → string `—`.  
- Empty agent list → table shows “No agents registered”.  
- Duplicate event id (either SSE or poll) – deduplicate by timestamp+agentId.

### 5. What it must NOT do

- No routing navigation.  
- No animations >150 ms.  
- No parent prop drilling (fully self-contained).  
- No editing forms.  
- No data persistence or caching beyond React state.