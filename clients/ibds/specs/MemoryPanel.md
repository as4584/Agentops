## MemoryPanel Specification

### 1. TypeScript Interfaces & Imports

```typescript
// Import types
import { Box, Flex, Button, Badge, Space, ScrollArea, Group, Text, Popover, CodeHighlight, Table, Progress } from '@mantine/core';
import { IconDatabase, IconTextWrapDisabled, IconArrowBack, IconTrash, IconEye, IconRefresh, IconClearAll, IconClock } from '@tabler/icons-react';
import { useState, useEffect, useCallback } from 'react';

// Data types
interface MemoryStats {
  total_size_mb: number;
}

interface MemoryItem {
  agent_id: string;
  namespace: string;
  size_bytes: number;
  memory: any;
}

interface EventLog {
  timestamp: string;
  type: string;
  summary: string;
}

interface Props {}

interface State {
  view: 'table' | 'inspector';
  currentNamespace: string | null;
  stats: MemoryStats | null;
  memoryItems: MemoryItem[];
  events: EventLog[];
  loading: {
    table: boolean;
    inspector: boolean;
    operations: Set<string>;
  };
  errors: {
    table?: string;
    inspector?: string;
    operations?: Map<string, string>;
  };
  maxSizeBytes: number;
}
```

### 2. Component Structure

```typescript
// Layout structure
<MemoryPanelRoot> // width: 100%, height: calc(100% - 12px*2)
  // Header Section - 36px height, padding: 0 12px
  <PanelHeader>
    <Group justify="space-between" align="center">
      <Text size="md" fw={700}>MEMORY</Text>
      <Badge>{stats?.total_size_mb || 0} MB</Badge>
      <Button 
        rightSection={<IconRefresh size={14} />}
        onClick={handleReindex}
        loading={loading.operations.has('reindex')}
      >
        Reindex
      </Button>
    </Group>
  </PanelHeader>

  // Main Content Area - height: calc(100% - 36px)
  <ContentContainer>
    // State: 'table' | 'inspector'
    {view === 'table' && (
      <TableView>
        <ScrollArea h="calc(100% - 200px)" type="hover"> // 200px reserved for events log
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th ta="center">agent_id</Table.Th>
                <Table.Th>namespace</Table.Th>
                <Table.Th>size</Table.Th>
                <Table.Th>actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              // rows with inline progress bars
            </Table.Tbody>
          </Table>
        </ScrollArea>
      </TableView>
    )}

    {view === 'inspector' && (
      <InspectorView>
        <ScrollArea h="calc(100% - 200px)">
          <Group mb="md">
            <Button leftSection={<IconArrowBack size={14} />} onClick={handleBack}>
              Back
            </Button>
            <Text fw={700}>{currentNamespace}</Text>
          </Group>
          <CodeHighlight code={namespaceData} language="json" />
        </ScrollArea>
      </InspectorView>
    )}

    // Events Log - height: 200px, border-top: 1px solid var(--mantine-color-gray-3)
    <EventsLog>
      <Group justify="space-between" align="center" px="md" pt="xs">
        <Text size="sm" fw={700}>Events</Text>
        <Button 
          rightSection={<IconClearAll size={14} />}
          onClick={handleClearEvents}
          loading={loading.operations.has('clear')}
          size="xs"
        >
          Clear log
        </Button>
      </Group>
      <ScrollArea h="calc(100% - 40px)" px="md">
        <Stack gap="xs">
          // event items with timestamp, type badge, summary
        </Stack>
      </ScrollArea>
    </EventsLog>
  </ContentContainer>
</MemoryPanelRoot>
```

### 3. Data Fetching

```typescript
// Endpoints
const ENDPOINTS = {
  stats: '/api/memory/stats',
  memoryList: '/api/memory',
  memoryNamespace: '/api/memory/',
  events: '/api/events',
  reindex: '/api/knowledge/reindex',
  clearEvents: '/api/memory/events'
};

// Fetch intervals
- Initial load: parallel fetch stats + memoryList + events
- Polling: stats, memoryList, events every 5000ms
- Inspector fetch: on-demand when namespace selected
- Clear events: single request, then refresh events
- Deletion: DELETE /memory/{namespace}, then refresh memoryList
- Reindex: POST /knowledge/reindex, then refresh stats + memoryList

// Loading states
- Table view: loading spinner centered in scroll area
- Inspector view: loading overlay over CodeHighlight
- Operations: button loading state, error toast on failure

// Error handling
- Failed fetches: inline error notice instead of empty table/code
- Operation errors: Mantine notification popover
```

### 4. Edge Cases to Handle

1. Empty states:
   - No memory items: "No memory namespaces" message centered
   - No events: "No events logged" message
   - Empty namespace: show "{}" in JSON viewer

2. Locked operations:
   - Disable delete button while delete operation pending for that namespace
   - Block inspector loads during in-flight requests
   - Queue API calls to prevent race conditions

3. Large data:
   - JSON viewer with max 50KB formatted output (truncated with ellipsis warning)
   - Event log capped at last 100 entries with "Show more" option
   - Progress bars handle 0-byte items (show 0% width, minimum 4px width clickable)

4. Network failures:
   - Exponential backoff for polls (max 3 attempts)
   - Stale data banner when backend unavailable
   - Retry button on fetch failure

5. Concurrent modifications:
   - Optimistic updates with rollback on failure
   - Version checking if API provides etag/last-modified

### 5. What It MUST NOT Do

- Never control other panels or global state
- Never modify URL or browser history
- Never cache data between component unmount/remount
- Never use localStorage or persistent storage
- Never implement search or filtering (let table handle natural overflow)
- Never allow batch operations
- Never show raw byte sizes (always format as MB)
- Never autoplay or auto-refresh inspector view
- Never implement pagination beyond scroll area lazy loading