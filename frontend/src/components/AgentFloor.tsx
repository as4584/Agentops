'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  SimpleGrid,
  Card,
  Text,
  Group,
  Badge,
  Stack,
  ThemeIcon,
  Tooltip,
  Box,
  Loader,
} from '@mantine/core';
import {
  IconBrain,
  IconCode,
  IconSearch,
  IconBarbell,
  IconMessage,
  IconHeartbeat,
  IconEye,
  IconZzz,
  IconAlertTriangle,
  IconRobot,
} from '@tabler/icons-react';
import { api, type AgentVisualSnapshot } from '@/lib/api';

// ---------------------------------------------------------------------------
// Pulse animation via global style injection
// ---------------------------------------------------------------------------
const PULSE_CSS = `
@keyframes agentfloor-pulse {
  0%   { box-shadow: 0 0 0 0 var(--pulse-color, rgba(100,180,255,0.4)); }
  70%  { box-shadow: 0 0 0 8px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
`;

if (typeof document !== 'undefined') {
  const id = 'agentfloor-pulse-style';
  if (!document.getElementById(id)) {
    const s = document.createElement('style');
    s.id = id;
    s.textContent = PULSE_CSS;
    document.head.appendChild(s);
  }
}

// ---------------------------------------------------------------------------
// Visual state → icon / colour / label mapping
// ---------------------------------------------------------------------------
const VISUAL_MAP: Record<string, { icon: typeof IconBrain; color: string; label: string }> = {
  idle:           { icon: IconZzz,            color: 'gray',   label: 'Idle' },
  thinking:       { icon: IconBrain,          color: 'blue',   label: 'Thinking' },
  coding:         { icon: IconCode,           color: 'violet', label: 'Coding' },
  researching:    { icon: IconSearch,         color: 'cyan',   label: 'Researching' },
  training:       { icon: IconBarbell,        color: 'orange', label: 'Training' },
  communicating:  { icon: IconMessage,        color: 'teal',   label: 'Communicating' },
  healing:        { icon: IconHeartbeat,      color: 'red',    label: 'Healing' },
  reviewing:      { icon: IconEye,            color: 'yellow', label: 'Reviewing' },
  error:          { icon: IconAlertTriangle,  color: 'red',    label: 'Error' },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
interface Props {
  /** If provided, use these snapshots instead of polling. */
  snapshots?: AgentVisualSnapshot[];
  /** Polling interval in ms (default 2000). Ignored if snapshots provided. */
  pollMs?: number;
}

export default function AgentFloor({ snapshots: externalSnapshots, pollMs = 2000 }: Props) {
  const [internal, setInternal] = useState<AgentVisualSnapshot[]>([]);
  const data = externalSnapshots ?? internal;

  const fetchVisual = useCallback(async () => {
    try {
      const vs = await api.visualStates();
      setInternal(vs);
    } catch { /* ignore — dashboard will show stale data */ }
  }, []);

  useEffect(() => {
    if (externalSnapshots) return;
    fetchVisual();
    const id = setInterval(fetchVisual, pollMs);
    return () => clearInterval(id);
  }, [externalSnapshots, fetchVisual, pollMs]);

  if (!data.length) {
    return (
      <Box ta="center" py="xl">
        <Loader size="sm" />
        <Text size="sm" c="dimmed" mt="sm">Loading agent floor&hellip;</Text>
      </Box>
    );
  }

  return (
    <SimpleGrid cols={{ base: 2, xs: 3, sm: 4, md: 6 }} spacing="sm">
      {data.map((snap) => {
        const vis = VISUAL_MAP[snap.visual_state] ?? VISUAL_MAP.idle;
        const Icon = vis.icon;
        const isActive = snap.visual_state !== 'idle';
        const isError = snap.visual_state === 'error';

        return (
          <Tooltip
            key={snap.agent_id}
            label={snap.visual_detail || vis.label}
            position="top"
            withArrow
          >
            <Card
              shadow="xs"
              withBorder
              padding="sm"
              ta="center"
              style={{
                borderColor: isActive
                  ? `var(--mantine-color-${vis.color}-5)`
                  : undefined,
                ['--pulse-color' as string]: `var(--mantine-color-${vis.color}-3)`,
                animation: isActive && !isError
                  ? 'agentfloor-pulse 1.6s ease-in-out infinite'
                  : undefined,
                transition: 'border-color 0.3s, box-shadow 0.3s',
              }}
            >
              <Stack align="center" gap={6}>
                <ThemeIcon
                  size="xl"
                  radius="xl"
                  variant={isActive ? 'filled' : 'light'}
                  color={vis.color}
                >
                  <Icon size={22} />
                </ThemeIcon>

                <Text size="xs" fw={600} truncate="end" maw="100%">
                  {snap.agent_id.replace(/_/g, ' ')}
                </Text>

                <Group gap={4} wrap="nowrap">
                  <Badge
                    size="xs"
                    variant={isActive ? 'filled' : 'outline'}
                    color={vis.color}
                  >
                    {vis.label}
                  </Badge>
                </Group>
              </Stack>
            </Card>
          </Tooltip>
        );
      })}
    </SimpleGrid>
  );
}
