1. TypeScript interface
```ts
// File: @/components/dashboard/ContentPanel.tsx
import { useEffect, useState, FC } from 'react';
import {
  Badge,
  SegmentedControl,
  ScrollArea,
  Group,
  Text,
  Button,
  Modal,
  TextInput,
  Center,
  Loader
} from '@mantine/core';
import { IconCheck, IconX } from '@tabler/icons-react';
import { API_BASE } from '@/lib/api';

// --- TYPES --------------
type Platform = 'tiktok' | 'youtube' | 'instagram' | 'linkedin';
type JobStatus =
  | 'DRAFT'
  | 'GENERATED'
  | 'AUDIO_READY'
  | 'VIDEO_READY'
  | 'CAPTIONED'
  | 'QA'
  | 'APPROVED'
  | 'SCHEDULED'
  | 'POSTED'
  | 'FAILED';

interface Job {
  id: string;
  topic: string;
  status: JobStatus;
  platforms: Platform[];
}

interface CalendarEntry {
  id: string;
  datetime: string;
  topic: string;
  platforms: Platform[];
}

interface ContentSummary {
  draft: number;
  running: number;
  done: number;
}

type View = 'Pipeline' | 'Calendar';
```

2. Component structure
```ts
const ContentPanel: FC = () => {
  // internal state
  const [view, setView] = useState<View>('Pipeline');
  const [pipelineJobs, setPipelineJobs] = useState<Job[]>([]);
  const [calendarJobs, setCalendarJobs] = useState<Record<string, CalendarEntry[]>>({});
  const [summary, setSummary] = useState<ContentSummary>({ draft: 0, running: 0, done: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectJobId, setRejectJobId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  // --- UI LAYOUT --------
  <Group justify="space-between" mb="md">
    <Group>
      <Text fw={700} size="md">CONTENT</Text>
      <Badge color="gray">{summary.draft} draft</Badge>
      <Badge color="blue">{summary.running} running</Badge>
      <Badge color="green">{summary.done} done</Badge>
    </Group>
    <SegmentedControl
      value={view}
      onChange={v => setView(v as View)}
      data={['Pipeline', 'Calendar']}
    />
  </Group>

  {view === 'Pipeline' && (
    <>
      <Group justify="flex-end" mb="sm">
        <Button onClick={runPipeline} disabled={loading}>
          Run Pipeline
        </Button>
      </Group>

      <ScrollArea h="100%">
        {loading && !pipelineJobs.length && <Center><Loader /></Center>}
        {error && <Text c="red">{error}</Text>}
        {pipelineJobs.map(job => (
          <Group key={job.id} justify="space-between" py="xs">
            <Group>
              <Text>{job.topic}</Text>
              {job.platforms.map(p => <Badge key={p} size="xs">{p}</Badge>)}
              <StatusBadge status={job.status} />
            </Group>

            {job.status === 'QA' && (
              <Group>
                <Button leftSection={<IconCheck size={14} />} onClick={() => approveJob(job.id)}>
                  Approve
                </Button>
                <Button leftSection={<IconX size={14} />} onClick={() => openRejectModal(job.id)}>
                  Reject
                </Button>
              </Group>
            )}
          </Group>
        ))}
      </ScrollArea>
    </>
  )}

  {view === 'Calendar' && (
    <ScrollArea h="100%">
      {loading && !Object.keys(calendarJobs).length && <Center><Loader /></Center>}
      {error && <Text c="red">{error}</Text>}
      {Object.entries(calendarJobs).map(([date, entries]) => (
        <Group key={date} direction="column" align="stretch">
          <Text fw={600} mt="md">{date}</Text>
          {entries.map(e => (
            <Group key={e.id} justify="space-between" py="xs">
              <Text>{e.topic} {e.datetime}</Text>
              {e.platforms.map(p => <Badge key={p} size="xs">{p}</Badge>)}
            </Group>
          ))}
        </Group>
      ))}
    </ScrollArea>
  )}

  <Modal opened={rejectModalOpen} onClose={() => setRejectModalOpen(false)} title="Reject reason">
    <TextInput
      value={rejectReason}
      onChange={e => setRejectReason(e.target.value)}
      placeholder="Reason for rejection"
    />
    <Group mt="sm">
      <Button onClick={submitReject}>Submit</Button>
    </Group>
  </Modal>
}
```

3. Data fetching
```ts
const fetchPipeline = async () => {
  const res = await fetch(`${API_BASE}/content/jobs`);
  if (!res.ok) throw new Error('Failed to fetch pipeline');
  const data: Job[] = await res.json();
  setPipelineJobs(data);
  // tally summary
  const draft = data.filter(j => j.status === 'DRAFT').length;
  const running = data.filter(j =>
    ['GENERATED', 'AUDIO_READY', 'VIDEO_READY', 'CAPTIONED', 'QA', 'APPROVED', 'SCHEDULED'].includes(j.status)
  ).length;
  const done = data.filter(j => ['POSTED'].includes(j.status)).length;
  setSummary({ draft, running, done });
};

const fetchCalendar = async () => {
  const res = await fetch(`${API_BASE}/content/calendar`);
  if (!res.ok) throw new Error('Failed to fetch calendar');
  const data: CalendarEntry[] = await res.json();
  const grouped: Record<string, CalendarEntry[]> = {};
  data.forEach(e => {
    const date = e.datetime.split('T')[0];
    (grouped[date] ||= []).push(e);
  });
  setCalendarJobs(grouped);
};

useEffect(() => {
  const load = () => {
    setLoading(true);
    const f = view === 'Pipeline' ? fetchPipeline : fetchCalendar;
    f().catch(e => setError(e.message)).finally(() => setLoading(false));
  };
  load();
  const interval = setInterval(load, 5000);
  return () => clearInterval(interval);
}, [view]);
```

4. Edge cases it must handle
- Zero jobs → shows empty scroll area, summary badges 0
- Server returns non-200 → displays short error message in-place
- Polling stops on unmount
- Duplicate identical data in response → overwrites cleanly
- Race condition: user switches tab while fetch in-flight → second fetch debounced by setInterval
- Reject reason empty → reject button disabled
- Job list > viewport height → vertical scroll
- Very long topic text doesn’t wrap layout (Mantine text truncates via ellipsis via theme)

5. What it must NOT do
- Own its padding (parent supplies)
- Routing / navigation changes
- Global state management
- Import from any other local component
- Export anything but default
- Modify or mutate job objects in-place; always replace arrays
- Render internal state variables outside scope
- Use Mantine Tabs, only SegmentedControl