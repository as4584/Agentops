1. TypeScript interface  
```ts
// PlanPanel.tsx  
import { ScrollArea, Badge, Button, TextInput, Textarea, Select, Skeleton, Collapse, Box, Group, Text, ActionIcon } from '@mantine/core';  
import { IconPlus, IconX, IconCheckbox, IconSquare, IconRefresh } from '@tabler/icons-react';  

type Goal = {  
  id: string;  
  title: string;  
  description: string;  
  priority: 'HIGH' | 'MED' | 'LOW';  
  created_at: string;  
  completed: boolean;  
};  

type Task = {  
  id: string;  
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';  
  task_id: string;  
  agent: string;  
  action: string;  
  created_at: string;  
  duration_ms: number | null;  
};  

type DriftStatus = {  
  state: 'GREEN' | 'YELLOW' | 'RED';  
  violations: {  
    severity: 'HIGH' | 'MED' | 'LOW';  
    invariant_id: string;  
    description: string;  
  }[];  
};  

type PlanPanelProps = {};  

type PlanPanelState = {  
  goals: Goal[];  
  reflectionText: string;  
  tasks: Task[];  
  drift: DriftStatus | null;  
  showAddForm: boolean;  
  newGoal: { title: string; description: string; priority: 'HIGH' | 'MED' | 'LOW' };  
  taskFilter: 'ALL' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';  
  showAllViolations: boolean;  
  loadingGoals: boolean;  
  loadingTasks: boolean;  
  loadingDrift: boolean;  
  polling: boolean;  
};  
```

2. Component layout  
- Fixed 36px header: label “PLAN”, badge with `goals.length`, right-aligned “Add Goal” button.  
- Section A — Soul Goals list: inside `ScrollArea.Autosize` with `maxHeight` set to available space.  
  - Each row: complete-checkbox, title (bold), description (1 line, `color="dimmed"`), priority badge, delete ×.  
  - Inline add-form (collapsed with `showAddForm`): `TextInput`, `Textarea`, `Select` for priority, “Save” & “Cancel” buttons.  
- Section B — Reflection:  
  - Collapsible header “Reflection” with chevron.  
  - Content: last reflection text (max 120px height) + “Trigger Reflection” button.  
  - Skeleton loader replaces content while `loadingGoals` or `polling`.  
- Section C — Task Queue table:  
  - Filter row: `Select` for status.  
  - Scrollable `Table` with columns: status badge | task_id mono truncated | agent | action | created relative | duration.  
  - Cancel × button on queued rows only.  
- Section D — Drift violations:  
  - Rendered only if `drift?.state !== 'GREEN'`.  
  - Compact list, max 5 items, “Show all” toggle.  
  - Badge color mapping: HIGH=red, MED=yellow, LOW=gray.  
- Panel root: `Box p={12}`.  
- Global 5s interval polling: `GET /soul/goals`, `GET /tasks`, `GET /drift/status`.

3. Data fetching  
- Initial fetch on mount: all three endpoints in parallel.  
- Poll every 5s while component mounted; abort on unmount.  
- Mutations:  
  - `POST /soul/goals` → on save inline form, refetch goals.  
  - `DELETE /soul/goals/{id}` → on delete icon, optimistic remove then refetch.  
  - `PATCH /soul/goals/{id}` → on checkbox toggle, optimistic update then refetch.  
  - `POST /soul/reflect` → on “Trigger Reflection” button, refetch goals & reflection text.  
  - `DELETE /tasks/{id}` → on cancel queued task, optimistic remove then refetch tasks.  
- Error handling: toast notification on any fetch/mutation fail; keep stale data.  
- Loading states: skeleton placeholders for goals, reflection, tasks, drift when first loading or polling.

4. Edge cases  
- Empty goals → show “No goals yet” placeholder row.  
- Reflection text null → show “No reflection generated”.  
- Drift violations null/empty → show “No violations”.  
- Task duration null → render “—”.  
- Long title/description → truncate with ellipsis, full text tooltip.  
- Rapid toggle of completion → debounce PATCH, ignore if goal deleted in meantime.  
- Network offline → stop polling, retry on reconnect.  
- Unmount during mutation → cancel fetch/abort controller.

5. Must NOT  
- Modify any data outside its own endpoints.  
- Manage UI state for other panels.  
- Implement routing, auth, or global theming.  
- Include any business logic beyond CRUD for goals/tasks/drift.