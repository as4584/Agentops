import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, Box, ScrollArea, ActionIcon } from '@mantine/core';
import { IconTrash, IconRefresh } from '@tabler/icons-react';

interface MemoryStats {
  total_namespaces: number;
  total_events: number;
  namespaces: Array<{ name: string; event_count: number; size_bytes: number }>;
}

function fmt(bytes: number) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

export default function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);

  const fetchStats = async () => {
    try {
      const r = await fetch(`${API_BASE}/memory/stats`);
      if (r.ok) setStats(await r.json());
    } catch {}
  };

  useEffect(() => {
    fetchStats();
    const iv = setInterval(fetchStats, 10000);
    return () => clearInterval(iv);
  }, []);

  const clearNamespace = async (ns: string) => {
    try {
      await fetch(`/api/memory/${ns}`, { method: 'DELETE' });
      fetchStats();
    } catch {}
  };

  return (
    <Stack gap={8} h="100%">
      <Group justify="space-between">
        <Text fw={700} size="sm" c="dimmed" tt="uppercase">Memory</Text>
        <ActionIcon size="xs" variant="subtle" onClick={fetchStats}>
          <IconRefresh size={12} />
        </ActionIcon>
      </Group>

      {stats && (
        <Group gap={16}>
          <Box>
            <Text size="xs" c="dimmed">Namespaces</Text>
            <Text size="sm" ff="monospace">{stats.total_namespaces}</Text>
          </Box>
          <Box>
            <Text size="xs" c="dimmed">Events</Text>
            <Text size="sm" ff="monospace">{stats.total_events.toLocaleString()}</Text>
          </Box>
        </Group>
      )}

      <ScrollArea flex={1}>
        <Stack gap={4}>
          {!stats && <Text size="xs" c="dimmed">Loading...</Text>}
          {stats?.namespaces.map((ns) => (
            <Group key={ns.name} justify="space-between" px={8} py={4}
              style={{ background: '#141619', borderRadius: 4 }}>
              <Box>
                <Text size="xs" fw={600}>{ns.name}</Text>
                <Text size="xs" c="dimmed">{ns.event_count} events · {fmt(ns.size_bytes)}</Text>
              </Box>
              <ActionIcon size="xs" variant="subtle" color="red"
                onClick={() => clearNamespace(ns.name)}>
                <IconTrash size={10} />
              </ActionIcon>
            </Group>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
