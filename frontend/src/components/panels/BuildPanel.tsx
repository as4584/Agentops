import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, Box, ScrollArea } from '@mantine/core';

interface WebgenProject {
  id: string;
  business_name: string;
  status: 'ready' | 'generated' | 'deploying' | 'deployed' | 'error';
  updated_at: string;
}

const statusColor = (s: string) =>
  s === 'deployed' ? 'green' : s === 'error' ? 'red' : s === 'deploying' ? 'blue' : 'teal';

const statusLabel = (s: string) =>
  s === 'deployed' ? 'deployed' : s === 'error' ? 'failed' : s === 'deploying' ? 'running' : s;

export default function BuildPanel() {
  const [projects, setProjects] = useState<WebgenProject[]>([]);

  const fetchProjects = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/webgen/projects`);
      if (r.ok) {
        const data = await r.json();
        setProjects(data.projects ?? []);
      }
    } catch {}
  };

  useEffect(() => {
    fetchProjects();
    const iv = setInterval(fetchProjects, 5000);
    return () => clearInterval(iv);
  }, []);

  const running = projects.filter((p) => p.status === 'deploying');
  const recent = projects.filter((p) => p.status !== 'deploying').slice(0, 10);

  return (
    <Stack gap={8} h="100%">
      <Text fw={700} size="sm" c="dimmed" tt="uppercase">WebGen Projects</Text>

      {running.length > 0 && (
        <Stack gap={6}>
          <Text size="xs" c="dimmed">Deploying ({running.length})</Text>
          {running.map((p) => (
            <Box key={p.id} px={8} py={6} style={{ background: '#141619', borderRadius: 4 }}>
              <Group justify="space-between">
                <Text size="xs" fw={600}>{p.business_name}</Text>
                <Badge size="xs" color="blue">deploying</Badge>
              </Group>
            </Box>
          ))}
        </Stack>
      )}

      <Text size="xs" c="dimmed">Recent ({recent.length})</Text>
      <ScrollArea flex={1}>
        <Stack gap={4}>
          {recent.length === 0 && <Text size="xs" c="dimmed">No projects yet</Text>}
          {recent.map((p) => (
            <Group key={p.id} justify="space-between" px={8} py={4}
              style={{ background: '#141619', borderRadius: 4 }}>
              <Box>
                <Text size="xs" fw={600}>{p.business_name}</Text>
                <Text size="xs" c="dimmed">{new Date(p.updated_at).toLocaleDateString()}</Text>
              </Box>
              <Badge size="xs" color={statusColor(p.status)}>{statusLabel(p.status)}</Badge>
            </Group>
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
