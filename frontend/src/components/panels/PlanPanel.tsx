import { API_BASE } from '@/lib/api';
import React, { useEffect, useState } from 'react';
import { Stack, Group, Text, Badge, Button, Textarea, Box, ScrollArea } from '@mantine/core';
import { IconPlus, IconRefresh } from '@tabler/icons-react';

interface Goal {
  id: string;
  title: string;
  description: string;
  priority: 'HIGH' | 'MED' | 'LOW';
  completed: boolean;
}

interface Task {
  id: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  agent: string;
  action: string;
}

const priorityColor = (p: string) =>
  p === 'HIGH' ? 'red' : p === 'MED' ? 'yellow' : 'blue';

export default function PlanPanel() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [newGoalTitle, setNewGoalTitle] = useState('');
  const [adding, setAdding] = useState(false);

  const fetchAll = async () => {
    try {
      const [gr, tr] = await Promise.all([
        fetch(`${API_BASE}/soul/goals`),
        fetch(`${API_BASE}/tasks`),
      ]);
      if (gr.ok) setGoals(await gr.json());
      if (tr.ok) setTasks(await tr.json());
    } catch {}
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, []);

  const addGoal = async () => {
    if (!newGoalTitle.trim()) return;
    try {
      await fetch('/api/soul/goals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newGoalTitle, priority: 'MED' }),
      });
      setNewGoalTitle('');
      setAdding(false);
      fetchAll();
    } catch {}
  };

  return (
    <Stack gap={8} h="100%">
      <Group justify="space-between">
        <Text fw={700} size="sm" c="dimmed" tt="uppercase">Plan</Text>
        <Group gap={6}>
          <Button size="xs" variant="subtle" leftSection={<IconPlus size={10} />}
            onClick={() => setAdding((v) => !v)}>
            Goal
          </Button>
          <Button size="xs" variant="subtle" p={4} onClick={fetchAll}>
            <IconRefresh size={12} />
          </Button>
        </Group>
      </Group>

      {adding && (
        <Box>
          <Textarea
            size="xs"
            placeholder="New goal title..."
            value={newGoalTitle}
            onChange={(e) => setNewGoalTitle(e.currentTarget.value)}
            autosize
            minRows={1}
          />
          <Group gap={6} mt={4}>
            <Button size="xs" onClick={addGoal}>Save</Button>
            <Button size="xs" variant="subtle" onClick={() => setAdding(false)}>Cancel</Button>
          </Group>
        </Box>
      )}

      <Text size="xs" c="dimmed">Goals</Text>
      <ScrollArea flex={1}>
        <Stack gap={4}>
          {goals.length === 0 && <Text size="xs" c="dimmed">No goals set</Text>}
          {goals.map((g) => (
            <Box key={g.id} px={8} py={4} style={{ background: '#141619', borderRadius: 4 }}>
              <Group justify="space-between">
                <Text size="xs" fw={600} td={g.completed ? 'line-through' : undefined}>{g.title}</Text>
                <Badge size="xs" color={priorityColor(g.priority)}>{g.priority}</Badge>
              </Group>
              {g.description && <Text size="xs" c="dimmed" lineClamp={2}>{g.description}</Text>}
            </Box>
          ))}
        </Stack>
      </ScrollArea>

      <Box style={{ borderTop: '1px solid #2a2d32', paddingTop: 8 }}>
        <Text size="xs" c="dimmed" mb={4}>Tasks</Text>
        <ScrollArea h={80}>
          <Stack gap={2}>
            {tasks.length === 0 && <Text size="xs" c="dimmed">Queue empty</Text>}
            {tasks.map((t) => (
              <Group key={t.id} gap={6} wrap="nowrap">
                <Badge size="xs" color={t.status === 'RUNNING' ? 'blue' : t.status === 'FAILED' ? 'red' : 'gray'}>
                  {t.status}
                </Badge>
                <Text size="xs" lineClamp={1}>[{t.agent}] {t.action}</Text>
              </Group>
            ))}
          </Stack>
        </ScrollArea>
      </Box>
    </Stack>
  );
}
