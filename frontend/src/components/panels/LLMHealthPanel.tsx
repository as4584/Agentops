'use client';

import { useEffect, useState } from 'react';
import { Badge, Card, Group, SimpleGrid, Text, Tooltip } from '@mantine/core';
import { api, type LLMHealthData, type ModelCircuitState } from '@/lib/api';

const POLL_MS = 15_000;

function badgeColor(state: ModelCircuitState): string {
  if (state.circuit_open) return 'red';
  if (!state.healthy || state.consecutive_failures > 0) return 'yellow';
  return 'green';
}

function badgeLabel(state: ModelCircuitState): string {
  if (state.circuit_open) return 'Circuit Open';
  if (!state.healthy || state.consecutive_failures > 0) return 'Degraded';
  return 'Healthy';
}

export default function LLMHealthPanel() {
  const [health, setHealth] = useState<LLMHealthData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      try {
        const data = await api.llmHealth();
        if (mounted) setHealth(data);
      } catch {
        if (mounted) setHealth({ circuit_states: {} });
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, POLL_MS);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const states = Object.values(health?.circuit_states ?? {});

  return (
    <Card shadow="sm" withBorder mb="lg" data-testid="llm-health-panel">
      <Group justify="space-between" mb="sm">
        <Text fw={600} size="sm" tt="uppercase" c="dimmed">LLM Circuit Health</Text>
        <Badge size="sm" variant="light">{states.length} models</Badge>
      </Group>

      {loading ? (
        <Text size="sm" c="dimmed">Loading model health…</Text>
      ) : states.length === 0 ? (
        <Text size="sm" c="dimmed">No circuit state data available.</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }}>
          {states.map((state) => (
            <Tooltip
              key={state.model_id}
              label={`failures=${state.consecutive_failures}${state.last_error ? ` · ${state.last_error}` : ''}`}
              withArrow
            >
              <Group justify="space-between" p="xs" style={{ border: '1px solid var(--mantine-color-dark-4)', borderRadius: 'var(--mantine-radius-sm)' }}>
                <Text size="xs" ff="monospace" truncate style={{ maxWidth: '70%' }}>{state.model_id}</Text>
                <Badge data-testid={`llm-health-badge-${state.model_id}`} size="xs" color={badgeColor(state)} variant="filled">
                  {badgeLabel(state)}
                </Badge>
              </Group>
            </Tooltip>
          ))}
        </SimpleGrid>
      )}
    </Card>
  );
}
