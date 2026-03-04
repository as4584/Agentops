import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, Progress, Box } from '@mantine/core';

interface SpendData {
  session_usd: number;
  ceiling_usd: number;
  model_breakdown: Record<string, number>;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
}

export default function CostPanel() {
  const [spend, setSpend] = useState<SpendData | null>(null);

  const fetchSpend = async () => {
    try {
      const r = await fetch(`${API_BASE}/orchestrator/spend`);
      if (r.ok) setSpend(await r.json());
    } catch {}
  };

  useEffect(() => {
    fetchSpend();
    const iv = setInterval(fetchSpend, 5000);
    return () => clearInterval(iv);
  }, []);

  const pct = spend ? Math.min((spend.session_usd / spend.ceiling_usd) * 100, 100) : 0;
  const barColor = pct >= 90 ? 'red' : pct >= 70 ? 'orange' : 'green';

  return (
    <Stack gap={8} h="100%">
      <Text fw={700} size="sm" c="dimmed" tt="uppercase">Cost</Text>

      {spend ? (
        <>
          <Box>
            <Group justify="space-between" mb={4}>
              <Text size="xs" fw={700} c={pct >= 90 ? 'red' : 'white'}>
                ${spend.session_usd.toFixed(4)}
              </Text>
              <Text size="xs" c="dimmed">/ ${spend.ceiling_usd.toFixed(2)} ceiling</Text>
            </Group>
            <Progress value={pct} color={barColor} size="sm" />
          </Box>

          <Stack gap={4}>
            <Group justify="space-between">
              <Text size="xs" c="dimmed">Total tokens</Text>
              <Text size="xs" ff="monospace">{spend.total_tokens.toLocaleString()}</Text>
            </Group>
            <Group justify="space-between">
              <Text size="xs" c="dimmed">Input / Output</Text>
              <Text size="xs" ff="monospace">
                {spend.input_tokens.toLocaleString()} / {spend.output_tokens.toLocaleString()}
              </Text>
            </Group>
          </Stack>

          {Object.keys(spend.model_breakdown).length > 0 && (
            <Box>
              <Text size="xs" c="dimmed" mb={4}>By model</Text>
              <Stack gap={2}>
                {Object.entries(spend.model_breakdown).map(([model, cost]) => (
                  <Group key={model} justify="space-between">
                    <Text size="xs" lineClamp={1} style={{ maxWidth: '60%' }}>{model}</Text>
                    <Text size="xs" ff="monospace">${(cost as number).toFixed(4)}</Text>
                  </Group>
                ))}
              </Stack>
            </Box>
          )}
        </>
      ) : (
        <Text size="xs" c="dimmed">No spend data</Text>
      )}
    </Stack>
  );
}
