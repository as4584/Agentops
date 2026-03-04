1. TypeScript interface / imports
```ts
import { Progress, Card, Table, Text, Badge, ScrollArea, Box, Group, Center } from '@mantine/core';
import { IconRefresh, IconCircleFilled } from '@tabler/icons-react';
import { useInterval } from '@mantine/hooks';
import { useEffect, useState } from 'react';

type ModelType = 'local' | 'cloud';

interface CostLog {
  time: string;          // ISO-8601
  model: string;         // short-name, e.g. 'gpt-3.5'
  modelType: ModelType;  // used to pick badge color
  task: string;
  tokensIn: number;
  tokensOut: number;
  cost: number;          // $
}

interface ModelBreakdown {
  local: number;         // 0–100
  cloud: number;
}

interface CostData {
  budgetPct: number;          // 0–100  (threshold source)
  spent: number;              // $
  remaining: number;          // $
  limit: number;              // $
  totalIn: number;            // tokens
  totalOut: number;           // tokens
  avgLatency: number;         // ms
  costPerRequest: number;     // $
  log: CostLog[];
  modelBreakdown: ModelBreakdown;
}

// component props (empty, everything internal)
interface CostPanelProps {}
```

2. Component structure / layout
```
<Box style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 12 }}>
  {/* Header 36px */}
  <Group h={36} position="apart" align="center" noWrap>
    <Text size="sm" fw={700} tt="uppercase">Cost</Text>
    <Badge
      size="sm"
      color={budgetPct < 60 ? 'green' : budgetPct <= 85 ? 'yellow' : 'red'}
    >
      {budgetPct.toFixed(0)}%
    </Badge>
  </Group>

  {/* Section A – Budget */}
  <Card p="xs" mb="xs">
    <Progress
      value={budgetPct}
      color={budgetPct < 60 ? 'green' : budgetPct <= 85 ? 'yellow' : 'red'}
      size="md"
    />
    <Group position="apart" mt={6}>
      <Metric label="Spent" value={spent} currency/>
      <Metric label="Remaining" value={remaining} currency/>
      <Metric label="Limit" value={limit} currency/>
    </Group>
  </Card>

  {/* Section B – 2×2 metrics */}
  <SimpleGrid cols={2} mb="xs">
    <MetricCard label="Total In" value={totalIn} suf="tokens"/>
    <MetricCard label="Total Out" value={totalOut} suf="tokens"/>
    <MetricCard label="Avg Latency" value={avgLatency} suf="ms"/>
    <MetricCard label="Cost/Request" value={costPerRequest} suf="$"/>
  </SimpleGrid>

  {/* Section C – Cost log */}
  <Card style={{ flex: 1, display: 'flex', flexDirection: 'column' }} p={0}>
    <ScrollArea style={{ flex: 1 }} offsetScrollBar>
      <Table highlightOnHover fontSize="xs">
        <thead>
          <tr>
            <th>Time</th>
            <th>Model</th>
            <th>Task</th>
            <th>Tokens</th>
            <th style={{ textAlign: 'right' }}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {log.map((row) => (
            <tr key={row.time + row.model}>
              <td>{formatTime(row.time)}</td>
              <td>
                <Badge
                  size="xs"
                  color={row.modelType === 'local' ? 'green' : 'blue'}
                  leftSection={<IconCircleFilled size={6}/>}
                >
                  {row.model}
                </Badge>
              </td>
              <td>{truncate(row.task, 24)}</td>
              <td>{`${row.tokensIn}+${row.tokensOut}`}</td>
              <td style={{ textAlign: 'right' }}>${row.cost.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </ScrollArea>
  </Card>

  {/* Section D – Model breakdown */}
  <Card p="xs" mt="xs">
    <Progress
      sections={[
        { value: modelBreakdown.local, color: 'green', label: 'Local' },
        { value: modelBreakdown.cloud, color: 'blue', label: 'Cloud' },
      ]}
      size="md"
    />
    <Center mt={4}>
      <Text size="xs" c="dimmed">
        Local: {modelBreakdown.local}% | Cloud: {modelBreakdown.cloud}%
      </Text>
    </Center>
  </Card>
</Box>
```
MetricCard internals: value rendered in JetBrains Mono 22px fw=700, label in Inter 11px fw=500 uppercase c="dimmed".

3. Data fetching
- Endpoint: `GET /analytics/costs` → returns `CostData`
- Polling: every 5 s via `useInterval` hook
- Fetcher: async function inside `useEffect` on mount; on callback executes `fetch().then(setData).catch(setError)`
- `loading` boolean shown as skeleton placeholders in metric cards and table only; never full-screen spinner
- `error` shows inline red text only in header row; does not block panel render

4. Edge cases handled
- `/analytics/costs` 4xx/5xx → keep previous data, set `error` banner, continue polling
- `budgetPct` > 100 → still render red badge & progress capped at 100 %
- Missing/empty log → render empty table body; no stub row
- `modelBreakdown` values don't sum to 100 → clamp each to 0-100 and show %-sum discrepancy in label
- Negative monetary or token values → render as-is; color logic still uses %-of-limit
- Rapid re-mount (HMR) → abort in-flight fetch via `AbortController` on unmount
- Token in+out display overflow: keep `12345+67890` pattern, no rounding until 8 digits

5. Must NOT
- expose any prop to control refresh rate or endpoint
- perform any write/mutation (no POST/PUT/DELETE)
- contain mini-chart library other than Mantine Progress
- add export/CSV buttons or row actions
- handle user auth; assumes valid cookie already present
- share state with sibling components; fully self-contained
- implement theme-switching or dark-mode toggles (obeys Mantine provider)
- include tooltips, popovers, or clickable model badges beyond color
- render anything outside its 12 px padded box (no outer margins)