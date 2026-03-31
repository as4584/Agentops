'use client';

import { useEffect, useState, type FC } from 'react';
import {
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  ScrollArea,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { IconCheck, IconPlayerPlay, IconX } from '@tabler/icons-react';
import { API_BASE } from '@/lib/api';

/* ── Types ─────────────────────────────────────────────── */

interface Job {
  job_id: string;
  topic: string;
  status: string;
  platform_targets: string[];
  created_at: string;
}

interface CalendarEntry {
  job_id: string;
  topic: string;
  status: string;
  scheduled_time: string | null;
  platform_targets: string[];
}

/* ── Status badge colour mapping ───────────────────────── */

const STATUS_COLORS: Record<string, string> = {
  draft: 'gray',
  generated: 'blue',
  audio_ready: 'indigo',
  video_ready: 'blue',
  captioned: 'grape',
  qa: 'yellow',
  approved: 'teal',
  scheduled: 'cyan',
  posted: 'green',
  failed: 'red',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge size="xs" color={STATUS_COLORS[status] ?? 'gray'} variant="light">
      {status}
    </Badge>
  );
}

/* ── Component ─────────────────────────────────────────── */

const ContentPanel: FC = () => {
  const [view, setView] = useState<'Pipeline' | 'Calendar'>('Pipeline');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<Job[]>([]);
  const [calendar, setCalendar] = useState<CalendarEntry[]>([]);

  // reject modal
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectJobId, setRejectJobId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  /* ── Fetchers ──────────────────────────────────────── */

  const fetchJobs = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/content/jobs`);
      if (!res.ok) throw new Error(`${res.status}`);
      setJobs(await res.json());
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const fetchCalendar = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/content/calendar`);
      if (!res.ok) throw new Error(`${res.status}`);
      setCalendar(await res.json());
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  /* ── Actions ───────────────────────────────────────── */

  const runPipeline = async () => {
    try {
      await fetch(`${API_BASE}/content/run`, { method: 'POST' });
      await fetchJobs();
    } catch {
      /* silent */
    }
  };

  const approveJob = async (id: string) => {
    try {
      await fetch(`${API_BASE}/content/jobs/${id}/approve`, { method: 'POST' });
      await fetchJobs();
    } catch {
      /* silent */
    }
  };

  const submitReject = async () => {
    if (!rejectJobId || !rejectReason.trim()) return;
    try {
      await fetch(`${API_BASE}/content/jobs/${rejectJobId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: rejectReason }),
      });
      setRejectOpen(false);
      setRejectJobId(null);
      setRejectReason('');
      await fetchJobs();
    } catch {
      /* silent */
    }
  };

  /* ── Polling ───────────────────────────────────────── */

  useEffect(() => {
    const load = view === 'Pipeline' ? fetchJobs : fetchCalendar;
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [view]);

  /* ── Summary counts ────────────────────────────────── */

  const draft = jobs.filter(j => j.status === 'draft').length;
  const active = jobs.filter(
    j => !['draft', 'posted', 'failed'].includes(j.status),
  ).length;
  const done = jobs.filter(j => j.status === 'posted').length;

  /* ── Render ────────────────────────────────────────── */

  return (
    <Stack gap={8} h="100%">
      <Group justify="space-between">
        <Text fw={700} size="sm" c="dimmed" tt="uppercase">
          Content
        </Text>
        <SegmentedControl
          size="xs"
          value={view}
          onChange={(v) => setView(v as 'Pipeline' | 'Calendar')}
          data={['Pipeline', 'Calendar']}
        />
      </Group>

      {error && (
        <Text size="xs" c="red">
          {error}
        </Text>
      )}

      {/* ── Pipeline view ───────────────────────────── */}
      {view === 'Pipeline' && (
        <>
          <Group gap={12}>
            <Text size="xs" c="dimmed">
              Draft {draft} &middot; Active {active} &middot; Done {done}
            </Text>
            <Button
              size="xs"
              variant="light"
              leftSection={<IconPlayerPlay size={14} />}
              onClick={runPipeline}
              loading={loading}
            >
              Run
            </Button>
          </Group>

          <ScrollArea style={{ flex: 1 }} offsetScrollbars>
            {loading && !jobs.length ? (
              <Center>
                <Loader size="sm" />
              </Center>
            ) : (
              jobs.map(job => (
                <Group key={job.job_id} justify="space-between" py={4}>
                  <Group gap={6}>
                    <Text size="sm">{job.topic || job.job_id}</Text>
                    <StatusBadge status={job.status} />
                    {job.platform_targets.map(p => (
                      <Badge key={p} size="xs" variant="outline">
                        {p}
                      </Badge>
                    ))}
                  </Group>

                  {job.status === 'qa' && (
                    <Group gap={4}>
                      <Button
                        size="xs"
                        variant="light"
                        color="teal"
                        leftSection={<IconCheck size={14} />}
                        onClick={() => approveJob(job.job_id)}
                      >
                        Approve
                      </Button>
                      <Button
                        size="xs"
                        variant="light"
                        color="red"
                        leftSection={<IconX size={14} />}
                        onClick={() => {
                          setRejectJobId(job.job_id);
                          setRejectOpen(true);
                        }}
                      >
                        Reject
                      </Button>
                    </Group>
                  )}
                </Group>
              ))
            )}
          </ScrollArea>
        </>
      )}

      {/* ── Calendar view ───────────────────────────── */}
      {view === 'Calendar' && (
        <ScrollArea style={{ flex: 1 }} offsetScrollbars>
          {loading && !calendar.length ? (
            <Center>
              <Loader size="sm" />
            </Center>
          ) : (
            calendar.map(entry => (
              <Group key={entry.job_id} justify="space-between" py={4}>
                <Group gap={6}>
                  <Text size="sm">{entry.topic || entry.job_id}</Text>
                  <StatusBadge status={entry.status} />
                </Group>
                <Text size="xs" c="dimmed">
                  {entry.scheduled_time
                    ? new Date(entry.scheduled_time).toLocaleString()
                    : '—'}
                </Text>
              </Group>
            ))
          )}
        </ScrollArea>
      )}

      {/* ── Reject modal ────────────────────────────── */}
      <Modal
        opened={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject reason"
        size="sm"
      >
        <TextInput
          value={rejectReason}
          onChange={e => setRejectReason(e.currentTarget.value)}
          placeholder="Reason for rejection"
        />
        <Group mt="sm" justify="flex-end">
          <Button onClick={submitReject} disabled={!rejectReason.trim()}>
            Submit
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
};

export default ContentPanel;
