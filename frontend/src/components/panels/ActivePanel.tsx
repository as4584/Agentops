import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, ScrollArea, Box, ActionIcon } from '@mantine/core';
import { IconRefresh, IconPlayerPlay, IconPlayerStop } from '@tabler/icons-react';

interface Agent {
  id: string;
  role: string;
  status: 'online' | 'idle' | 'error';
  last_active: string;
}

interface SystemStatus {
  connected: boolean;
  uptime: string;
  llm: string;
  drift: string;
}

interface StreamEvent {
  timestamp: string;
  type: string;
  agent_id: string | null;
  detail: string;
}

const statusColor = (s: string) =>
  s === 'online' ? 'green' : s === 'error' ? 'red' : 'yellow';

export default function ActivePanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [events, setEvents] = useState<StreamEvent[]>([]);

  const fetchAll = async () => {
    try {
      const [sr, ar] = await Promise.all([
        fetch(`${API_BASE}/status`),
        fetch(`${API_BASE}/agents`),
      ]);
      if (sr.ok) {
        const data = await sr.json();
        // /status returns {uptime_seconds, drift_report, agents, ...}
        setStatus({
          connected: true,
          uptime: `${Math.floor((data.uptime_seconds ?? 0) / 60)}m uptime`,
          llm: 'ollama',
          drift: data.drift_report?.status?.toLowerCase() ?? 'unknown',
        });
      }
      if (ar.ok) setAgents(await ar.json());
    } catch {}
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 5000);
    const es = new EventSource(`${API_BASE}/stream/activity`);
    es.onmessage = (e) => {
      try {
        const ev: StreamEvent = JSON.parse(e.data);
        setEvents((prev) => [ev, ...prev].slice(0, 50));
      } catch {}
    };
    return () => { clearInterval(iv); es.close(); };
  }, []);

  return (
    <Stack gap={8} h="100%">
      <Group justify="space-between">
        <Text fw={700} size="sm" c="dimmed" tt="uppercase">Active</Text>
        <Group gap={6}>
          {status && (
            <Badge size="xs" color={status.connected ? 'green' : 'red'}>
              {status.connected ? 'Connected' : 'Offline'}
            </Badge>
          )}
          <ActionIcon size="xs" variant="subtle" onClick={fetchAll}>
            <IconRefresh size={12} />
          </ActionIcon>
        </Group>
      </Group>

      {status && (
        <Group gap={8}>
          <Text size="xs" c="dimmed">{status.uptime}</Text>
          <Badge size="xs" color="blue">{status.llm}</Badge>
          <Badge size="xs" color={status.drift === 'sync' ? 'green' : 'orange'}>{status.drift}</Badge>
        </Group>
      )}

      <ScrollArea flex={1}>
        <Stack gap={4}>
          {agents.length === 0 && <Text size="xs" c="dimmed">No agents running</Text>}
          {agents.map((a) => (
            <Group key={a.id} justify="space-between" px={8} py={4}
              style={{ background: '#141619', borderRadius: 4 }}>
              <Box>
                <Text size="xs" fw={600}>{a.id}</Text>
                <Text size="xs" c="dimmed">{a.role}</Text>
              </Box>
              <Group gap={4}>
                <Badge size="xs" color={statusColor(a.status)}>{a.status}</Badge>
                <ActionIcon size="xs" variant="subtle"><IconPlayerPlay size={10} /></ActionIcon>
                <ActionIcon size="xs" variant="subtle" color="red"><IconPlayerStop size={10} /></ActionIcon>
              </Group>
            </Group>
          ))}
        </Stack>
      </ScrollArea>

      <Box style={{ borderTop: '1px solid #2a2d32', paddingTop: 8 }}>
        <Text size="xs" c="dimmed" mb={4}>Events</Text>
        <ScrollArea h={80}>
          <Stack gap={2}>
            {events.length === 0 && <Text size="xs" c="dimmed">No events yet</Text>}
            {events.map((ev, i) => (
              <Group key={i} gap={6} wrap="nowrap">
                <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                  {new Date(ev.timestamp).toLocaleTimeString()}
                </Text>
                <Badge size="xs" variant="outline">{ev.type}</Badge>
                <Text size="xs" lineClamp={1}>{ev.detail}</Text>
              </Group>
            ))}
          </Stack>
        </ScrollArea>
      </Box>
    </Stack>
  );
}
