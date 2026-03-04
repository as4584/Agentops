import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, Box, ScrollArea, Progress } from '@mantine/core';

interface BuildJob {
  id: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  site_name: string;
  progress: number;
  message: string;
  started_at: string;
}

const statusColor = (s: string) =>
  s === 'done' ? 'green' : s === 'failed' ? 'red' : s === 'running' ? 'blue' : 'gray';

export default function BuildPanel() {
  const [jobs, setJobs] = useState<BuildJob[]>([]);

  const fetchJobs = async () => {
    try {
      const r = await fetch(`${API_BASE}/webgen/jobs`);
      if (r.ok) setJobs(await r.json());
    } catch {}
  };

  useEffect(() => {
    fetchJobs();
    const iv = setInterval(fetchJobs, 3000);
    return () => clearInterval(iv);
  }, []);

  const running = jobs.filter((j) => j.status === 'running');
  const recent = jobs.filter((j) => j.status !== 'running').slice(0, 10);

  return (
    <Stack gap={8} h="100%">
      <Text fw={700} size="sm" c="dimmed" tt="uppercase">Build</Text>

      {running.length > 0 && (
        <Stack gap={6}>
          <Text size="xs" c="dimmed">Running ({running.length})</Text>
          {running.map((j) => (
            <Box key={j.id} px={8} py={6} style={{ background: '#141619', borderRadius: 4 }}>
              <Group justify="space-between" mb={4}>
                <Text size="xs" fw={600}>{j.site_name}</Text>
                <Badge size="xs" color="blue">running</Badge>
              </Group>
              <Progress value={j.progress} size="xs" color="blue" mb={4} animated />
              <Text size="xs" c="dimmed" lineClamp={1}>{j.message}</Text>
            </Box>
          ))}
        </Stack>
      )}

      <Text size="xs" c="dimmed">Recent</Text>
      <ScrollArea flex={1}>
        <Stack gap={4}>
          {recent.length === 0 && <Text size="xs" c="dimmed">No builds yet</Text>}
          {recent.map((j) => (
            <Group key={j.id} justify="space-between" px={8} py={4}
              style={{ background: '#141619', borderRadius: 4 }}>
              <Box>
                <Text size="xs" fw={600}>{j.site_name}</Text>
                <Text size="xs" c="dimmed">{j.message}</Text>
              </Box>
              <Badge size="xs" color={statusColor(j.status)}>{j.status}</Badge>
            </Group>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
