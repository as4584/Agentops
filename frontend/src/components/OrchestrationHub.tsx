'use client';

/**
 * OrchestrationHub — Mission Control workspace tab.
 *
 * Three-tier org-chart:
 *   1. Founder bar  — you, the human decision-maker
 *   2. Orchad card  — soul_core orchestrator with embedded chat + task queue
 *   3. Teams row    — Dev (code_review + devops) | Social (comms_agent)
 */

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge, Box, Card, Grid, Group, Loader, Paper, ScrollArea,
  Select, Stack, Text, Textarea, ThemeIcon, Tooltip,
} from '@mantine/core';
import {
  IconBolt, IconBrain, IconCheck, IconCode,
  IconRefresh, IconRobot, IconSend, IconUser, IconX,
} from '@tabler/icons-react';
import ModelSwitcher from './ModelSwitcher';
import { api } from '@/lib/api';
import type { AgentDefinition, AgentState, TaskItem } from '@/lib/api';

// ── Persona definitions ────────────────────────────────────────────────────
const PERSONAS = {
  orchad: {
    agentIds: ['soul_core'],
    label: 'Orchad',
    subtitle: 'Strategic Orchestrator',
    color: '#1a82ff',
    accent: 'rgba(26,130,255,0.10)',
    icon: IconBrain,
    defaultModel: 'lex',
    chatAgent: 'auto',
  },
  dev: {
    agentIds: ['code_review_agent', 'devops_agent'],
    label: 'Dev Team',
    subtitle: 'Engineering & Infrastructure',
    color: '#22c55e',
    accent: 'rgba(34,197,94,0.10)',
    icon: IconCode,
    defaultModel: 'mistral:7b',
    chatAgent: 'code_review_agent',
  },
  social: {
    agentIds: ['comms_agent'],
    label: 'Social & Content',
    subtitle: 'Content Creation & Publishing',
    color: '#f59e0b',
    accent: 'rgba(245,158,11,0.10)',
    icon: IconBolt,
    defaultModel: 'llama3.2',
    chatAgent: 'comms_agent',
  },
} as const;

type PersonaKey = keyof typeof PERSONAS;

// ── Types ──────────────────────────────────────────────────────────────────
type ChatMsg = {
  role: 'user' | 'agent';
  content: string;
  agent?: string;
  timestamp: string;
};

// ── Helpers ────────────────────────────────────────────────────────────────
function statusColor(s?: string): string {
  switch (s) {
    case 'ACTIVE': case 'READY': return '#22c55e';
    case 'WORKING': case 'RUNNING': return '#3b82f6';
    case 'ERROR': case 'FAILED': return '#ef4444';
    default: return '#6b7280';
  }
}

function StatusDot({ status }: { status?: string }) {
  const color = statusColor(status);
  const animate = status === 'ACTIVE' || status === 'WORKING' || status === 'RUNNING';
  return (
    <Box
      w={8} h={8}
      style={{
        borderRadius: '50%',
        background: color,
        flexShrink: 0,
        animation: animate ? 'pulse 2s ease-in-out infinite' : 'none',
        boxShadow: animate ? `0 0 6px ${color}` : 'none',
      }}
    />
  );
}

function fmtTime(ts: string): string {
  try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); } catch { return ts; }
}

// ── Agent team card (Dev / Social) ─────────────────────────────────────────
function TeamCard({
  personaKey,
  agentStates,
  tasks,
  agents,
}: {
  personaKey: 'dev' | 'social';
  agentStates: AgentState[];
  tasks: TaskItem[];
  agents: AgentDefinition[];
}) {
  const p = PERSONAS[personaKey];
  const Icon = p.icon;
  const [model, setModel] = useState<string>(p.defaultModel);

  const myAgentIds = p.agentIds as readonly string[];
  const myStates = agentStates.filter(s => myAgentIds.includes(s.agent_id));
  const myTasks = tasks.filter(t => myAgentIds.includes(t.agent_id ?? '') && (t.status === 'QUEUED' || t.status === 'RUNNING'));
  const primaryState = myStates[0];

  const overallStatus = myStates.some(s => s.status === 'ACTIVE' || s.status === 'WORKING')
    ? 'ACTIVE'
    : myStates.length > 0 ? (myStates[0].status ?? 'IDLE') : 'IDLE';

  return (
    <Card
      withBorder
      h="100%"
      style={{
        background: 'var(--mantine-color-dark-8)',
        borderColor: 'var(--mantine-color-dark-5)',
        borderTop: `2px solid ${p.color}`,
        overflow: 'hidden',
      }}
    >
      <Stack gap="sm" h="100%">
        {/* Header */}
        <Group justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            <ThemeIcon size={28} radius="sm" style={{ background: p.accent, color: p.color, border: `1px solid ${p.color}30` }}>
              <Icon size={14} />
            </ThemeIcon>
            <div>
              <Text fw={700} size="sm" style={{ color: p.color }}>{p.label}</Text>
              <Text size="xs" c="dimmed">{p.subtitle}</Text>
            </div>
          </Group>
          <Group gap={6} wrap="nowrap">
            <StatusDot status={overallStatus} />
            <Text size="xs" c="dimmed">{overallStatus}</Text>
          </Group>
        </Group>

        {/* Agent list */}
        <Stack gap={4}>
          {myAgentIds.map(id => {
            const st = myStates.find(s => s.agent_id === id);
            const def = agents.find(a => a.agent_id === id);
            return (
              <Group key={id} gap={8} justify="space-between" wrap="nowrap">
                <Group gap={6} wrap="nowrap">
                  <StatusDot status={st?.status} />
                  <Text size="xs" ff="monospace" c="dimmed">{id.replace(/_/g, ' ')}</Text>
                </Group>
                <Group gap={6} wrap="nowrap">
                  {def && <Text size="xs" c="dimmed" truncate style={{ maxWidth: 120 }}>{def.role}</Text>}
                  {st && <Text size="xs" c="dimmed" ff="monospace">{st.total_actions} actions</Text>}
                </Group>
              </Group>
            );
          })}
        </Stack>

        {/* Model switcher */}
        <Group gap={8} align="center">
          <Text size="xs" c="dimmed">Model:</Text>
          <ModelSwitcher agentId={p.chatAgent} value={model} onChange={setModel} />
        </Group>

        {/* Current work */}
        <Box style={{ borderTop: '1px solid var(--mantine-color-dark-5)', paddingTop: 8, flex: 1, minHeight: 0 }}>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={6}>Current Work</Text>
          <ScrollArea h={100} type="auto">
            <Stack gap={4}>
              {myTasks.length === 0 ? (
                <Text size="xs" c="dimmed">No active tasks</Text>
              ) : myTasks.map(t => (
                <Paper
                  key={t.id}
                  p={6}
                  radius="sm"
                  style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-5)' }}
                >
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Badge
                      size="xs"
                      color={t.status === 'RUNNING' ? 'blue' : 'gray'}
                      variant={t.status === 'RUNNING' ? 'filled' : 'light'}
                    >
                      {t.status}
                    </Badge>
                    <Text size="xs" truncate style={{ flex: 1 }}>{t.action}</Text>
                  </Group>
                </Paper>
              ))}
            </Stack>
          </ScrollArea>
        </Box>
      </Stack>
    </Card>
  );
}

// ── Main component ──────────────────────────────────────────────────────────
export default function OrchestrationHub({ agents }: { agents: AgentDefinition[] }) {
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);

  // Orchad chat state
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [startTime, setStartTime] = useState<number | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Model state for Orchad
  const [orchadModel, setOrchadModel] = useState<string>(PERSONAS.orchad.defaultModel);

  // ── Polling ──────────────────────────────────────────────────────────────
  const poll = useCallback(async () => {
    try {
      const [st, td] = await Promise.all([
        api.status().catch(() => null),
        api.tasks(50).catch(() => null),
      ]);
      if (st) setAgentStates(st.agents ?? []);
      if (td) setTasks(td.tasks ?? []);
    } catch {}
  }, []);

  useEffect(() => {
    poll();
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, [poll]);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    if (!startTime) { setElapsed(0); return; }
    const iv = setInterval(() => setElapsed(Math.round((Date.now() - startTime) / 1000)), 500);
    return () => clearInterval(iv);
  }, [startTime]);

  // ── Send message ──────────────────────────────────────────────────────────
  const send = async (e: FormEvent) => {
    e.preventDefault();
    const msg = input.trim();
    if (!msg || loading) return;
    setInput('');
    setMessages(p => [...p, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
    setLoading(true);
    setStartTime(Date.now());
    try {
      const res = await api.chat(PERSONAS.orchad.chatAgent, msg);
      setMessages(p => [...p, {
        role: 'agent', content: res.message, agent: res.agent_id,
        timestamp: new Date().toISOString(),
      }]);
    } catch (err) {
      setMessages(p => [...p, {
        role: 'agent', content: `Error: ${err instanceof Error ? err.message : 'Unknown error'}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setLoading(false);
      setStartTime(null);
      poll();
    }
  };

  // ── Derived ───────────────────────────────────────────────────────────────
  const orchadState = agentStates.find(s => s.agent_id === 'soul_core');
  const orchadTasks = tasks.filter(
    t => ['soul_core'].includes(t.agent_id ?? '') && (t.status === 'QUEUED' || t.status === 'RUNNING')
  );
  const recentOrchad = tasks.filter(
    t => ['soul_core'].includes(t.agent_id ?? '') && (t.status === 'COMPLETED' || t.status === 'FAILED')
  ).slice(-5);

  return (
    <Stack gap="sm">
      {/* ── Tier 0: Founder ──────────────────────────────────────────────── */}
      <Card
        withBorder
        py={10} px={16}
        style={{
          background: 'linear-gradient(90deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.02) 100%)',
          borderColor: 'var(--mantine-color-dark-4)',
          borderTop: '2px solid rgba(255,255,255,0.15)',
        }}
      >
        <Group justify="space-between">
          <Group gap={12}>
            <ThemeIcon size={36} radius="md" style={{ background: 'rgba(255,255,255,0.07)', color: 'white', border: '1px solid rgba(255,255,255,0.15)' }}>
              <IconUser size={18} />
            </ThemeIcon>
            <div>
              <Group gap={8}>
                <Text fw={700} size="sm">You — Founder</Text>
                <Badge size="xs" variant="dot" color="green">LIVE</Badge>
              </Group>
              <Text size="xs" c="dimmed">Overseeing Operations · Decision Maker</Text>
            </div>
          </Group>
          <Text size="xs" c="dimmed" ff="monospace">{new Date().toLocaleTimeString()}</Text>
        </Group>
      </Card>

      {/* ── Tier 1: Orchad ───────────────────────────────────────────────── */}
      <Card
        withBorder
        style={{
          background: 'var(--mantine-color-dark-8)',
          borderColor: 'var(--mantine-color-dark-5)',
          borderTop: `2px solid ${PERSONAS.orchad.color}`,
          minHeight: 460,
        }}
      >
        {/* Orchad header */}
        <Group justify="space-between" mb="sm" pb="sm" wrap="nowrap"
          style={{ borderBottom: '1px solid var(--mantine-color-dark-5)' }}>
          <Group gap={10} wrap="nowrap">
            <ThemeIcon size={32} radius="sm" style={{ background: PERSONAS.orchad.accent, color: PERSONAS.orchad.color, border: `1px solid ${PERSONAS.orchad.color}30` }}>
              <IconBrain size={16} />
            </ThemeIcon>
            <div>
              <Group gap={8}>
                <Text fw={700} size="sm" style={{ color: PERSONAS.orchad.color }}>Orchad</Text>
                <Text size="xs" c="dimmed">Strategic Orchestrator</Text>
              </Group>
              <Text size="xs" c="dimmed" ff="monospace">soul_core</Text>
            </div>
          </Group>
          <Group gap={10} wrap="nowrap">
            <ModelSwitcher agentId="soul_core" value={orchadModel} onChange={setOrchadModel} />
            <Group gap={6}>
              <StatusDot status={orchadState?.status} />
              <Text size="xs" c="dimmed">{orchadState?.status ?? 'IDLE'}</Text>
            </Group>
            {orchadState && (
              <Tooltip label={`${orchadState.total_actions} total actions · ${orchadState.error_count} errors`}>
                <Text size="xs" c="dimmed" ff="monospace" style={{ cursor: 'default' }}>
                  {orchadState.total_actions} acts
                </Text>
              </Tooltip>
            )}
          </Group>
        </Group>

        {/* Orchad body: chat + queue */}
        <Grid gutter="sm">
          {/* Chat */}
          <Grid.Col span={{ base: 12, sm: 8 }}>
            <Stack gap={0} style={{ height: 380 }}>
              {/* Messages */}
              <ScrollArea style={{ flex: 1 }} type="auto" mb={8}>
                <Stack gap="xs" p={4}>
                  {messages.length === 0 && (
                    <Stack align="center" py="xl" gap="xs">
                      <ThemeIcon size={40} radius="xl" style={{ background: PERSONAS.orchad.accent, color: PERSONAS.orchad.color }}>
                        <IconBrain size={20} />
                      </ThemeIcon>
                      <Text size="sm" fw={600} ta="center">Command Orchad</Text>
                      <Text size="xs" c="dimmed" ta="center" maw={320}>
                        Issue tasks, ask for status reports, or direct strategic decisions through your AI orchestrator.
                      </Text>
                      <Group gap={6} mt={4}>
                        {[
                          'What\'s the current system status?',
                          'Summarize all active agent work',
                          'What should we prioritize today?',
                        ].map(q => (
                          <Paper
                            key={q}
                            p={6}
                            radius="sm"
                            style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-4)', cursor: 'pointer' }}
                            onClick={() => setInput(q)}
                          >
                            <Text size="xs" c="dimmed">{q}</Text>
                          </Paper>
                        ))}
                      </Group>
                    </Stack>
                  )}
                  {messages.map((m, i) => (
                    <Group key={i} gap={6} align="flex-start"
                      style={{ justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                      {m.role === 'agent' && (
                        <ThemeIcon size={24} radius="xl" style={{ background: PERSONAS.orchad.accent, color: PERSONAS.orchad.color, flexShrink: 0, marginTop: 2 }}>
                          <IconBrain size={12} />
                        </ThemeIcon>
                      )}
                      <Paper
                        p="sm"
                        radius="md"
                        style={{
                          maxWidth: '78%',
                          background: m.role === 'user' ? PERSONAS.orchad.color : 'var(--mantine-color-dark-7)',
                          border: m.role === 'agent' ? '1px solid var(--mantine-color-dark-5)' : 'none',
                        }}
                      >
                        {m.role === 'agent' && m.agent && (
                          <Text size="xs" fw={600} mb={2} style={{ color: PERSONAS.orchad.color }}>{m.agent.replace(/_/g, ' ')}</Text>
                        )}
                        <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }} c={m.role === 'user' ? 'white' : undefined}>
                          {m.content}
                        </Text>
                        <Text size="xs" c={m.role === 'user' ? 'rgba(255,255,255,0.5)' : 'dimmed'} ta={m.role === 'user' ? 'right' : 'left'} mt={4}>
                          {fmtTime(m.timestamp)}
                        </Text>
                      </Paper>
                      {m.role === 'user' && (
                        <ThemeIcon size={24} radius="xl" style={{ background: PERSONAS.orchad.color, flexShrink: 0, marginTop: 2 }}>
                          <IconSend size={10} />
                        </ThemeIcon>
                      )}
                    </Group>
                  ))}
                  {loading && (
                    <Group gap={6} align="flex-start">
                      <ThemeIcon size={24} radius="xl" style={{ background: PERSONAS.orchad.accent, color: PERSONAS.orchad.color, flexShrink: 0 }}>
                        <IconBrain size={12} />
                      </ThemeIcon>
                      <Paper p="sm" radius="md" style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-5)' }}>
                        <Group gap={6}><Loader size="xs" color="blue" /><Text size="xs" c="dimmed">Thinking… {elapsed}s</Text></Group>
                      </Paper>
                    </Group>
                  )}
                  <div ref={chatEndRef} />
                </Stack>
              </ScrollArea>

              {/* Input */}
              <form onSubmit={send}>
                <Paper
                  p={6}
                  radius="md"
                  style={{ background: 'var(--mantine-color-dark-7)', border: `1px solid ${PERSONAS.orchad.color}40` }}
                >
                  <Group gap={6} wrap="nowrap" align="flex-end">
                    <Textarea
                      style={{ flex: 1 }}
                      size="sm"
                      placeholder="Command Orchad… (Enter to send, Shift+Enter for newline)"
                      value={input}
                      onChange={e => setInput(e.currentTarget.value)}
                      disabled={loading}
                      autosize
                      minRows={1}
                      maxRows={4}
                      onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e as unknown as FormEvent); }
                      }}
                      styles={{
                        input: { background: 'transparent', border: 'none', resize: 'none', padding: '4px 0' },
                      }}
                    />
                    <Group gap={4} style={{ flexShrink: 0 }}>
                      {messages.length > 0 && (
                        <Paper
                          p={4}
                          radius="sm"
                          style={{ cursor: 'pointer', background: 'transparent' }}
                          onClick={() => setMessages([])}
                        >
                          <IconX size={14} color="var(--mantine-color-dimmed)" />
                        </Paper>
                      )}
                      <Paper
                        component="button"
                        type="submit"
                        p={6}
                        radius="sm"
                        style={{
                          background: loading ? 'transparent' : PERSONAS.orchad.color,
                          border: 'none',
                          cursor: loading ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {loading ? <Loader size={14} color="blue" /> : <IconSend size={14} color="white" />}
                      </Paper>
                    </Group>
                  </Group>
                </Paper>
              </form>
            </Stack>
          </Grid.Col>

          {/* Task queue */}
          <Grid.Col span={{ base: 12, sm: 4 }}>
            <Stack gap={0} style={{ height: 380 }}>
              <Group justify="space-between" mb={6}>
                <Text size="xs" c="dimmed" fw={600} tt="uppercase">Queue</Text>
                <Badge size="xs" variant="light" color="blue">{orchadTasks.length} active</Badge>
              </Group>
              <ScrollArea style={{ flex: 1 }} type="auto">
                <Stack gap={4}>
                  {orchadTasks.length === 0 && recentOrchad.length === 0 && (
                    <Text size="xs" c="dimmed">No tasks in queue</Text>
                  )}
                  {orchadTasks.map(t => (
                    <Paper key={t.id} p={8} radius="sm"
                      style={{ background: 'var(--mantine-color-dark-7)', border: `1px solid ${t.status === 'RUNNING' ? PERSONAS.orchad.color + '50' : 'var(--mantine-color-dark-5)'}` }}>
                      <Group gap={6} mb={2}>
                        <Badge size="xs" color={t.status === 'RUNNING' ? 'blue' : 'gray'} variant={t.status === 'RUNNING' ? 'filled' : 'light'}>
                          {t.status}
                        </Badge>
                      </Group>
                      <Text size="xs" lineClamp={2}>{t.action}</Text>
                    </Paper>
                  ))}
                  {recentOrchad.length > 0 && (
                    <>
                      <Text size="xs" c="dimmed" mt={8} fw={500}>Recent</Text>
                      {recentOrchad.map(t => (
                        <Paper key={t.id} p={8} radius="sm"
                          style={{ background: 'var(--mantine-color-dark-8)', border: '1px solid var(--mantine-color-dark-5)', opacity: 0.7 }}>
                          <Group gap={6} mb={2}>
                            <Badge size="xs" color={t.status === 'COMPLETED' ? 'green' : 'red'} variant="light">
                              {t.status}
                            </Badge>
                          </Group>
                          <Text size="xs" c="dimmed" lineClamp={2}>{t.action}</Text>
                        </Paper>
                      ))}
                    </>
                  )}
                </Stack>
              </ScrollArea>
            </Stack>
          </Grid.Col>
        </Grid>
      </Card>

      {/* ── Tier 2: Teams ────────────────────────────────────────────────── */}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <TeamCard personaKey="dev" agentStates={agentStates} tasks={tasks} agents={agents} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6 }}>
          <TeamCard personaKey="social" agentStates={agentStates} tasks={tasks} agents={agents} />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
