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
  Badge, Box, Card, Divider, Grid, Group, Loader, Paper, ScrollArea,
  Stack, Text, Textarea, ThemeIcon, Tooltip, Collapse, ActionIcon,
} from '@mantine/core';
import {
  IconBolt, IconBrain, IconCheck, IconCode, IconChevronDown, IconChevronRight,
  IconCircle, IconCircleFilled, IconExternalLink, IconGitBranch, IconLink, IconPlayerStop, IconRobot, IconSend,
  IconUser, IconX, IconBook, IconPlugConnected, IconPlugConnectedX,
  IconShield, IconServer,
} from '@tabler/icons-react';
import ModelSwitcher from './ModelSwitcher';
import { api, ApiError, API_BASE } from '@/lib/api';
import type { AgentDefinition, AgentState, TaskItem } from '@/lib/api';
import { useAdaptivePolling } from '@/lib/useAdaptivePolling';

// ── Persona definitions ────────────────────────────────────────────────────
const PERSONAS = {
  orchad: {
    agentIds: ['soul_core'],
    label: 'Orchad',
    subtitle: 'Strategic Orchestrator',
    color: '#1a82ff',
    accent: 'rgba(26,130,255,0.10)',
    icon: IconBrain,
    defaultModel: 'qwen2.5-coder:7b',
    chatAgent: 'soul_core',
  },
  dev: {
    agentIds: ['code_review_agent', 'devops_agent', 'coding_agent'],
    dotAgents: [
      { id: 'code_review_agent', label: 'Code Review' },
      { id: 'devops_agent', label: 'DevOps' },
      { id: 'coding_agent', label: 'Coding' },
      { id: 'webgen', label: 'WebGen' },
    ],
    label: 'Dev Team',
    subtitle: 'Engineering & Infrastructure',
    color: '#22c55e',
    accent: 'rgba(34,197,94,0.10)',
    icon: IconCode,
    defaultModel: 'mistral:7b',
    chatAgent: 'code_review_agent',
  },
  social: {
    agentIds: ['comms_agent', 'cs_agent'],
    contentStages: [
      { id: 'intake', label: 'Idea' },
      { id: 'script', label: 'Script' },
      { id: 'voice', label: 'Voice' },
      { id: 'media', label: 'Media' },
      { id: 'caption', label: 'Caption' },
      { id: 'qa', label: 'QA' },
      { id: 'publish', label: 'Publish' },
    ],
    label: 'Social & Support',
    subtitle: 'Content, Comms & Customer',
    color: '#f59e0b',
    accent: 'rgba(245,158,11,0.10)',
    icon: IconBolt,
    defaultModel: 'llama3.2',
    chatAgent: 'comms_agent',
  },
  ops: {
    agentIds: ['monitor_agent', 'self_healer_agent', 'security_agent', 'data_agent', 'it_agent', 'ocr_agent', 'knowledge_agent'],
    dotAgents: [
      { id: 'monitor_agent', label: 'Monitor' },
      { id: 'self_healer_agent', label: 'Healer' },
      { id: 'security_agent', label: 'Security' },
      { id: 'data_agent', label: 'Data' },
      { id: 'it_agent', label: 'IT' },
      { id: 'ocr_agent', label: 'OCR' },
      { id: 'knowledge_agent', label: 'Knowledge' },
    ],
    label: 'Ops & Intelligence',
    subtitle: 'Infra, Security & Data',
    color: '#a855f7',
    accent: 'rgba(168,85,247,0.10)',
    icon: IconShield,
    defaultModel: 'llama3.2',
    chatAgent: 'knowledge_agent',
  },
} as const;

type PersonaKey = keyof typeof PERSONAS;

// ── Types ──────────────────────────────────────────────────────────────────
type OrdoTrace = {
  lane: string;
  confidence: number;
  grounded_signal: string;
  inferred: boolean;
  assessment: string;
};

type ChatMsg = {
  role: 'user' | 'agent';
  content: string;
  agent?: string;
  timestamp: string;
  ordo_trace?: OrdoTrace;
  // Error metadata — populated when the chat request fails
  error_meta?: {
    request_id?: string;
    status?: number;
    selected_model?: string;
    last_live_step?: string;
    elapsed_s?: number;
  };
  sources?: string[];
  routing_method?: string;
  selected_model?: string;
  answering_model?: string;
  runtime_model?: string;
  execution_role?: string;
  model_source?: string;
  model_used?: string;
  drift_status?: string;
  run_id?: string;
  webgen_project_slug?: string;
  webgen_project_id?: string;
};

// ── Webgen run-state localStorage persistence ──────────────────────────────
const WEBGEN_RUN_LS_KEY = 'agentop_webgen_run_v1';
type WebgenRunCache = { runId: string; startedAt: number; phase: string };
function saveWebgenRun(runId: string, startedAt: number, phase: string): void {
  try { localStorage.setItem(WEBGEN_RUN_LS_KEY, JSON.stringify({ runId, startedAt, phase })); } catch { /* quota */ }
}
function loadWebgenRun(): WebgenRunCache | null {
  try {
    const raw = localStorage.getItem(WEBGEN_RUN_LS_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as WebgenRunCache;
    // Expire after 2 hours
    if (Date.now() - data.startedAt > 2 * 60 * 60 * 1000) { clearWebgenRun(); return null; }
    return data;
  } catch { return null; }
}
function clearWebgenRun(): void {
  try { localStorage.removeItem(WEBGEN_RUN_LS_KEY); } catch { /* ignore */ }
}

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

function formatModelLabel(model?: string | null): string {
  return model?.trim() || 'unknown';
}

function buildModelMetaTooltip(msg: Pick<ChatMsg, 'selected_model' | 'answering_model' | 'runtime_model' | 'execution_role' | 'model_source'>): string {
  const lines = [
    `Selected: ${formatModelLabel(msg.selected_model)}`,
    `Answering: ${formatModelLabel(msg.answering_model)}`,
    `Runtime: ${formatModelLabel(msg.runtime_model)}`,
  ];
  if (msg.execution_role) lines.push(`Role: ${msg.execution_role}`);
  if (msg.model_source) lines.push(`Source: ${msg.model_source}`);
  return lines.join('\n');
}

// ── Collapsible Ordo Reasoning panel ──────────────────────────────────────
function OrdoPanel({
  trace,
  answeringModel,
  runtimeModel,
  executionRole,
  modelSource,
  selectedModel,
}: {
  trace: OrdoTrace;
  answeringModel?: string;
  runtimeModel?: string;
  executionRole?: string;
  modelSource?: string;
  selectedModel?: string;
}) {
  const [open, setOpen] = useState(false);
  const confColor = trace.confidence >= 0.75 ? 'teal' : trace.confidence >= 0.5 ? 'yellow' : 'red';
  const modelTooltip = buildModelMetaTooltip({
    selected_model: selectedModel,
    answering_model: answeringModel,
    runtime_model: runtimeModel,
    execution_role: executionRole,
    model_source: modelSource,
  });
  return (
    <Box mt={6} style={{ borderTop: '1px solid var(--mantine-color-dark-5)' }}>
      <Group
        gap={6}
        pt={4}
        style={{ cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen(o => !o)}
      >
        <IconBrain size={10} style={{ color: 'rgba(26,130,255,0.7)', flexShrink: 0 }} />
        <Text size="xs" c="dimmed" fw={500}>Ordo</Text>
        <Badge size="xs" variant="outline" color={confColor}>{Math.round(trace.confidence * 100)}%</Badge>
        <Badge size="xs" variant="dot" color="gray">{trace.lane}</Badge>
        {trace.inferred && <Badge size="xs" color="orange" variant="light">inferred</Badge>}
        {answeringModel && (
          <Tooltip label={modelTooltip} multiline maw={320}>
            <Badge size="xs" color="grape" variant="light">via {formatModelLabel(answeringModel)}</Badge>
          </Tooltip>
        )}
        <ActionIcon size="xs" variant="transparent" color="gray" ml="auto">
          {open ? <IconChevronDown size={10} /> : <IconChevronRight size={10} />}
        </ActionIcon>
      </Group>
      <Collapse in={open}>
        <Box pt={4} pb={2}>
          <Text size="xs" c="dimmed" ff="monospace">↳ {trace.grounded_signal}</Text>
          <Text size="xs" c="dimmed" mt={2}>{trace.assessment}</Text>
        </Box>
      </Collapse>
    </Box>
  );
}

// ── Handoff dot strip ────────────────────────────────────────────────────────
function getHandoffPath(agentId: string): Array<{ label: string; active: boolean }> {
  const hop = (label: string, active = true) => ({ label, active });
  if (agentId === 'soul_core') return [hop('Orchad')];
  if (agentId === 'webgen') return [hop('Orchad'), hop('Dev Team'), hop('WebGen')];
  if (['code_review_agent', 'devops_agent', 'coding_agent'].includes(agentId))
    return [hop('Orchad'), hop('Dev Team'), hop(agentId.replace(/_agent$/, '').replace(/_/g, ' '))];
  if (agentId === 'comms_agent') return [hop('Orchad'), hop('Social'), hop('Comms')];
  if (agentId === 'knowledge_agent') return [hop('Orchad'), hop('Knowledge')];
  return [hop('Orchad'), hop(agentId.replace(/_/g, ' '))];
}

function HandoffDots({ agentId, webgenStage }: { agentId?: string; webgenStage?: string }) {
  if (!agentId || agentId === 'soul_core') return null;
  const path = getHandoffPath(agentId);
  const stages = ['clone_recon', 'clone_learn', 'planning', 'seo', 'aeo', 'qa', 'build', 'export'];
  const stageLabels: Record<string, string> = { clone_recon: 'Recon', clone_learn: 'Learn', planning: 'Plan', seo: 'SEO', aeo: 'AEO', qa: 'QA', build: 'Build', export: 'Export' };
  const stageIdx = webgenStage ? stages.indexOf(webgenStage) : -1;
  return (
    <Box mt={6} mb={2}>
      <Group gap={0} wrap="nowrap" align="center">
        {path.map((hop, i) => (
          <Group key={hop.label} gap={0} wrap="nowrap" align="center">
            {i > 0 && <Box w={16} h={1} style={{ background: 'var(--mantine-color-dark-4)', flexShrink: 0 }} />}
            <Stack gap={2} align="center" style={{ flexShrink: 0 }}>
              <Box w={8} h={8} style={{ borderRadius: '50%', background: hop.active ? '#22c55e' : 'var(--mantine-color-dark-4)', boxShadow: hop.active ? '0 0 6px #22c55e' : 'none' }} />
              <Text size="xs" c="dimmed" style={{ fontSize: 9, whiteSpace: 'nowrap' }}>{hop.label}</Text>
            </Stack>
          </Group>
        ))}
      </Group>
      {agentId === 'webgen' && (
        <Group gap={0} wrap="nowrap" align="center" mt={4} ml={16}>
          {stages.map((s, i) => (
            <Group key={s} gap={0} wrap="nowrap" align="center">
              {i > 0 && <Box w={12} h={1} style={{ background: 'var(--mantine-color-dark-5)', flexShrink: 0 }} />}
              <Stack gap={2} align="center" style={{ flexShrink: 0 }}>
                <Box w={6} h={6} style={{ borderRadius: '50%', background: i < stageIdx ? '#1a82ff40' : i === stageIdx ? '#1a82ff' : 'transparent', border: `1px solid ${i <= stageIdx ? '#1a82ff' : 'var(--mantine-color-dark-4)'}`, boxShadow: i === stageIdx ? '0 0 5px #1a82ff' : 'none' }} />
                <Text size="xs" c="dimmed" style={{ fontSize: 8, whiteSpace: 'nowrap' }}>{stageLabels[s] || s}</Text>
              </Stack>
            </Group>
          ))}
        </Group>
      )}
    </Box>
  );
}

// ── 3-tier routing pills ─────────────────────────────────────────────────────────────
function RoutingPills({ routingMethod }: { routingMethod?: string }) {
  const [open, setOpen] = useState(false);
  if (!routingMethod || routingMethod === 'direct' || routingMethod === 'webgen_intent') return null;
  const cHit = routingMethod === 'c_fast';
  const lexHit = routingMethod.startsWith('lex');
  const kwHit = routingMethod === 'keyword';
  const label = cHit ? 'c-fast' : lexHit ? 'lex' : kwHit ? 'keyword' : routingMethod;
  return (
    <Box mt={4}>
      <Group gap={4} style={{ cursor: 'pointer', userSelect: 'none', display: 'inline-flex' }} onClick={() => setOpen(o => !o)}>
        <IconGitBranch size={9} style={{ color: 'var(--mantine-color-dimmed)' }} />
        <Text size="xs" c="dimmed" style={{ fontSize: 10 }}>⚡ routed via {label}</Text>
        <IconChevronDown size={9} style={{ color: 'var(--mantine-color-dimmed)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
      </Group>
      <Collapse in={open}>
        <Group gap={4} mt={4}>
          {[
            { label: 'C-filter', hit: cHit, reached: true },
            { label: 'Lex', hit: lexHit, reached: !cHit },
            { label: 'Keyword', hit: kwHit, reached: !cHit && !lexHit },
          ].map(t => (
            <Badge key={t.label} size="xs" variant={t.hit ? 'filled' : 'outline'} color={t.hit ? 'teal' : t.reached ? 'gray' : 'dark'} style={{ opacity: t.reached ? 1 : 0.4 }}>
              {t.label} {t.hit ? '✓' : t.reached ? '—' : '×'}
            </Badge>
          ))}
        </Group>
      </Collapse>
    </Box>
  );
}

// ── OpenClaw full status card ────────────────────────────────────────────────────
type DiscordStatus = { enabled: boolean; connected: boolean; token_set: boolean; last_routed_agent?: string };

function OpenClawStatusCard() {
  const [status, setStatus] = useState<DiscordStatus | null>(null);
  const [error, setError] = useState(false);
  const fetchStatus = useCallback(() => {
    fetch('/api/proxy/discord/status')
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => { setStatus(d); setError(false); })
      .catch(() => setError(true));
  }, []);
  useAdaptivePolling({
    intervalMs: 20000,
    onTick: fetchStatus,
  });
  const color = '#5865f2';
  const connected = status?.connected;
  return (
    <Card withBorder h="100%" style={{ background: 'var(--mantine-color-dark-8)', borderColor: 'var(--mantine-color-dark-5)', borderTop: `2px solid ${color}`, overflow: 'hidden' }}>
      <Stack gap="sm" h="100%">
        <Group justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            <ThemeIcon size={28} radius="sm" style={{ background: `${color}20`, color, border: `1px solid ${color}30` }}><IconRobot size={14} /></ThemeIcon>
            <div>
              <Text fw={700} size="sm" style={{ color }}>OpenClaw</Text>
              <Text size="xs" c="dimmed">Discord · Telegram · Slack</Text>
            </div>
          </Group>
          <Group gap={6} wrap="nowrap">
            <StatusDot status={connected ? 'ACTIVE' : 'IDLE'} />
            <Text size="xs" c="dimmed">{connected ? 'LIVE' : 'OFFLINE'}</Text>
          </Group>
        </Group>
        <Divider color="dark.5" />
        <Stack gap={6}>
          {[
            { label: 'Discord bot', ok: !error && !!status?.token_set },
            { label: 'Gateway bridge', ok: !error && !!status?.enabled },
            { label: 'Connected', ok: !error && !!connected },
          ].map(row => (
            <Group key={row.label} gap={8} justify="space-between">
              <Text size="xs" c="dimmed">{row.label}</Text>
              {row.ok ? <IconPlugConnected size={12} style={{ color: '#22c55e' }} /> : <IconPlugConnectedX size={12} style={{ color: '#6b7280' }} />}
            </Group>
          ))}
        </Stack>
        {status?.last_routed_agent && (
          <Box mt={4} pt={6} style={{ borderTop: '1px solid var(--mantine-color-dark-5)' }}>
            <Text size="xs" c="dimmed">Last routed to:</Text>
            <Text size="xs" ff="monospace" c={color}>{status.last_routed_agent.replace(/_/g, ' ')}</Text>
          </Box>
        )}
        {!status && !error && <Text size="xs" c="dimmed" style={{ opacity: 0.5 }}>Loading…</Text>}
        {error && <Text size="xs" c="dimmed" style={{ opacity: 0.5 }}>Bot not started</Text>}
      </Stack>
    </Card>
  );
}

// ── Dev Team card — dot row ──────────────────────────────────────────────────
function DevTeamCard({
  agentStates, tasks, agents, reactSteps, webgenStage, elapsed, model, onModelChange,
}: {
  agentStates: AgentState[];
  tasks: TaskItem[];
  agents: AgentDefinition[];
  reactSteps: Record<string, { thought: string; tool_calls: string[]; step: number; timestamp: string }>;
  webgenStage?: string;
  elapsed?: number;
  model: string;
  onModelChange: (modelId: string) => void;
}) {
  const p = PERSONAS.dev;
  const Icon = p.icon;
  const myStates = agentStates.filter(s => (p.agentIds as readonly string[]).includes(s.agent_id));
  const myTasks = tasks.filter(t => (p.agentIds as readonly string[]).includes(t.agent_id ?? '') && (t.status === 'QUEUED' || t.status === 'RUNNING'));
  const overallStatus = myStates.some(s => s.status === 'ACTIVE' || s.status === 'WORKING') ? 'ACTIVE' : myStates.length > 0 ? (myStates[0].status ?? 'IDLE') : 'IDLE';
  const webgenStages = ['clone_recon', 'clone_learn', 'planning', 'seo', 'aeo', 'qa', 'build', 'export'];
  const webgenLabels: Record<string, string> = { clone_recon: 'Recon', clone_learn: 'Learn', planning: 'Plan', seo: 'SEO', aeo: 'AEO', qa: 'QA', build: 'Build', export: 'Export' };
  const stageIdx = webgenStage ? webgenStages.indexOf(webgenStage) : -1;

  return (
    <Card withBorder h="100%" style={{ background: 'var(--mantine-color-dark-8)', borderColor: 'var(--mantine-color-dark-5)', borderTop: `2px solid ${p.color}`, overflow: 'hidden' }}>
      <Stack gap="sm" h="100%">
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

        {/* Dot row: one dot per agent + webgen */}
        <Group gap={0} wrap="nowrap">
          {p.dotAgents.map((da, i) => {
            const st = agentStates.find(s => s.agent_id === da.id);
            const isActive = st?.status === 'ACTIVE' || st?.status === 'WORKING' || (da.id === 'webgen' && !!webgenStage) || (da.id === 'code_review_agent' && !!webgenStage);
            const isDone = !isActive && (st?.total_actions ?? 0) > 0;
            const color = isActive ? '#22c55e' : isDone ? '#22c55e60' : 'var(--mantine-color-dark-4)';
            return (
              <Group key={da.id} gap={0} wrap="nowrap" align="center">
                {i > 0 && <Box w={12} h={1} style={{ background: 'var(--mantine-color-dark-5)' }} />}
                <Stack gap={2} align="center">
                  <Box w={10} h={10} style={{ borderRadius: '50%', background: color, border: `1px solid ${isActive ? '#22c55e' : 'var(--mantine-color-dark-4)'}`, boxShadow: isActive ? '0 0 6px #22c55e' : 'none', flexShrink: 0 }} />
                  <Text size="xs" c="dimmed" style={{ fontSize: 9, whiteSpace: 'nowrap' }}>{da.label}</Text>
                </Stack>
              </Group>
            );
          })}
        </Group>

        {/* WebGen stage sub-dots — expands when webgen running */}
        {webgenStage && (
          <Group gap={8} wrap="nowrap" align="center">
            <Group gap={0} wrap="nowrap" ml={4}>
              {webgenStages.map((s, i) => (
                <Group key={s} gap={0} wrap="nowrap" align="center">
                  {i > 0 && <Box w={10} h={1} style={{ background: 'var(--mantine-color-dark-5)' }} />}
                  <Stack gap={2} align="center">
                    <Box w={7} h={7} style={{
                      borderRadius: '50%',
                      background: i < stageIdx ? '#1a82ff40' : i === stageIdx ? '#1a82ff' : 'transparent',
                      border: `1px solid ${i <= stageIdx ? '#1a82ff' : 'var(--mantine-color-dark-4)'}`,
                      boxShadow: i === stageIdx ? '0 0 5px #1a82ff' : 'none',
                    }} />
                    <Text size="xs" c="dimmed" style={{ fontSize: 8, whiteSpace: 'nowrap' }}>{webgenLabels[s] || s}</Text>
                  </Stack>
                </Group>
              ))}
            </Group>
            {elapsed != null && elapsed > 0 && (
              <Text size="xs" c="blue.4" ff="monospace" style={{ fontSize: 10, opacity: 0.85 }}>
                {elapsed}s
              </Text>
            )}
          </Group>
        )}

        <Group gap={8} align="center">
          <Text size="xs" c="dimmed">Model:</Text>
          <ModelSwitcher teamId="dev" value={model} onChange={onModelChange} />
        </Group>
        <Text size="xs" c="dimmed" mt={-6}>Applies to 3 agents</Text>

        {/* Live reasoning */}
        {(() => {
          const latestStep = (p.agentIds as readonly string[]).map(id => reactSteps[id]).filter(Boolean).sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];
          if (!latestStep?.thought) return null;
          return (
            <Paper p={8} radius="sm" style={{ background: `${p.color}10`, border: `1px solid ${p.color}30` }}>
              <Group gap={6} mb={4} wrap="nowrap">
                <Badge size="xs" color="violet" variant="light">thinking</Badge>
                <Text size="xs" c="dimmed" ff="monospace">step {latestStep.step}</Text>
                {latestStep.tool_calls.length > 0 && <Badge size="xs" variant="outline" color="gray">{latestStep.tool_calls[0]}</Badge>}
              </Group>
              <Text size="xs" c="dimmed" lineClamp={2}>{latestStep.thought}</Text>
            </Paper>
          );
        })()}

        <Box style={{ borderTop: '1px solid var(--mantine-color-dark-5)', paddingTop: 8, flex: 1, minHeight: 0 }}>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={6}>Current Work</Text>
          <ScrollArea h={120} type="auto">
            <Stack gap={4}>
              {myTasks.length === 0 ? <Text size="xs" c="dimmed">No active tasks</Text> : myTasks.map(t => (
                <Paper key={t.id} p={6} radius="sm" style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-5)' }}>
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Badge size="xs" color={t.status === 'RUNNING' ? 'blue' : 'gray'} variant={t.status === 'RUNNING' ? 'filled' : 'light'}>{t.status}</Badge>
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

// ── Social & Content card — dot pipeline ────────────────────────────────────
function SocialTeamCard({
  agentStates, tasks, reactSteps, contentStage, model, onModelChange,
}: {
  agentStates: AgentState[];
  tasks: TaskItem[];
  reactSteps: Record<string, { thought: string; tool_calls: string[]; step: number; timestamp: string }>;
  contentStage?: string;
  model: string;
  onModelChange: (modelId: string) => void;
}) {
  const p = PERSONAS.social;
  const Icon = p.icon;
  const myStates = agentStates.filter(s => (p.agentIds as readonly string[]).includes(s.agent_id));
  const myTasks = tasks.filter(t => (p.agentIds as readonly string[]).includes(t.agent_id ?? '') && (t.status === 'QUEUED' || t.status === 'RUNNING'));
  const overallStatus = myStates.some(s => s.status === 'ACTIVE' || s.status === 'WORKING') ? 'ACTIVE' : myStates.length > 0 ? (myStates[0].status ?? 'IDLE') : 'IDLE';

  const stageNames = p.contentStages.map(s => s.id);
  const stageIdx = contentStage ? (stageNames as string[]).indexOf(contentStage) : -1;

  return (
    <Card withBorder h="100%" style={{ background: 'var(--mantine-color-dark-8)', borderColor: 'var(--mantine-color-dark-5)', borderTop: `2px solid ${p.color}`, overflow: 'hidden' }}>
      <Stack gap="sm" h="100%">
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

        {/* Content pipeline dot row */}
        <Group gap={0} wrap="nowrap">
          {p.contentStages.map((stage, i) => {
            // isActive requires both the SSE stage event AND at least one agent in
            // ACTIVE/WORKING state from the 5-second poll. This prevents stale SSE
            // events from lighting dots when the pipeline has already stopped.
            const pipelineIsRunning = myStates.some(s => s.status === 'ACTIVE' || s.status === 'WORKING');
            const isActive = contentStage === stage.id && pipelineIsRunning;
            const isDone = stageIdx > i;
            const color = isActive ? p.color : isDone ? `${p.color}60` : 'var(--mantine-color-dark-4)';
            return (
              <Group key={stage.id} gap={0} wrap="nowrap" align="center">
                {i > 0 && <Box w={8} h={1} style={{ background: 'var(--mantine-color-dark-5)' }} />}
                <Stack gap={2} align="center">
                  <Box w={9} h={9} style={{ borderRadius: '50%', background: color, border: `1px solid ${isActive ? p.color : isDone ? `${p.color}60` : 'var(--mantine-color-dark-4)'}`, boxShadow: isActive ? `0 0 6px ${p.color}` : 'none', flexShrink: 0 }} />
                  <Text size="xs" c="dimmed" style={{ fontSize: 9, whiteSpace: 'nowrap' }}>{stage.label}</Text>
                </Stack>
              </Group>
            );
          })}
        </Group>

        <Group gap={8} align="center">
          <Text size="xs" c="dimmed">Model:</Text>
          <ModelSwitcher teamId="social" value={model} onChange={onModelChange} />
        </Group>
        <Text size="xs" c="dimmed" mt={-6}>Applies to comms + support</Text>

        {(() => {
          const latestStep = (p.agentIds as readonly string[]).map(id => reactSteps[id]).filter(Boolean).sort((a, b) => b.timestamp.localeCompare(a.timestamp))[0];
          if (!latestStep?.thought) return null;
          return (
            <Paper p={8} radius="sm" style={{ background: `${p.color}10`, border: `1px solid ${p.color}30` }}>
              <Group gap={6} mb={4} wrap="nowrap">
                <Badge size="xs" color="violet" variant="light">thinking</Badge>
                <Text size="xs" c="dimmed" ff="monospace">step {latestStep.step}</Text>
              </Group>
              <Text size="xs" c="dimmed" lineClamp={2}>{latestStep.thought}</Text>
            </Paper>
          );
        })()}

        <Box style={{ borderTop: '1px solid var(--mantine-color-dark-5)', paddingTop: 8, flex: 1, minHeight: 0 }}>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={6}>Current Work</Text>
          <ScrollArea h={120} type="auto">
            <Stack gap={4}>
              {myTasks.length === 0 ? <Text size="xs" c="dimmed">No active tasks</Text> : myTasks.map(t => (
                <Paper key={t.id} p={6} radius="sm" style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-5)' }}>
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Badge size="xs" color={t.status === 'RUNNING' ? 'blue' : 'gray'} variant={t.status === 'RUNNING' ? 'filled' : 'light'}>{t.status}</Badge>
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

// ── Ops & Intelligence card ───────────────────────────────────────────────
function OpsTeamCard({
  agentStates, tasks,
}: {
  agentStates: AgentState[];
  tasks: TaskItem[];
}) {
  const p = PERSONAS.ops;
  const Icon = p.icon;
  const myStates = agentStates.filter(s => (p.agentIds as readonly string[]).includes(s.agent_id));
  const myTasks = tasks.filter(t => (p.agentIds as readonly string[]).includes(t.agent_id ?? '') && (t.status === 'QUEUED' || t.status === 'RUNNING'));
  const overallStatus = myStates.some(s => s.status === 'ACTIVE' || s.status === 'WORKING') ? 'ACTIVE' : myStates.length > 0 ? (myStates[0].status ?? 'IDLE') : 'IDLE';

  return (
    <Card withBorder h="100%" style={{ background: 'var(--mantine-color-dark-8)', borderColor: 'var(--mantine-color-dark-5)', borderTop: `2px solid ${p.color}`, overflow: 'hidden' }}>
      <Stack gap="sm" h="100%">
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

        {/* Dot row */}
        <Group gap={0} wrap="nowrap" style={{ flexWrap: 'wrap', gap: 4 }}>
          {p.dotAgents.map((da) => {
            const st = myStates.find(s => s.agent_id === da.id);
            const isActive = st?.status === 'ACTIVE' || st?.status === 'WORKING';
            const isDone = !isActive && (st?.total_actions ?? 0) > 0;
            const color = isActive ? p.color : isDone ? `${p.color}60` : 'var(--mantine-color-dark-4)';
            return (
              <Stack key={da.id} gap={2} align="center" style={{ minWidth: 36 }}>
                <Box w={9} h={9} style={{ borderRadius: '50%', background: color, border: `1px solid ${isActive ? p.color : 'var(--mantine-color-dark-4)'}`, boxShadow: isActive ? `0 0 6px ${p.color}` : 'none' }} />
                <Text size="xs" c="dimmed" style={{ fontSize: 9, whiteSpace: 'nowrap' }}>{da.label}</Text>
              </Stack>
            );
          })}
        </Group>

        <Box style={{ borderTop: '1px solid var(--mantine-color-dark-5)', paddingTop: 8, flex: 1, minHeight: 0 }}>
          <Text size="xs" c="dimmed" fw={600} tt="uppercase" mb={6}>Current Work</Text>
          <ScrollArea h={120} type="auto">
            <Stack gap={4}>
              {myTasks.length === 0 ? <Text size="xs" c="dimmed">No active tasks</Text> : myTasks.map(t => (
                <Paper key={t.id} p={6} radius="sm" style={{ background: 'var(--mantine-color-dark-7)', border: '1px solid var(--mantine-color-dark-5)' }}>
                  <Group gap={6} justify="space-between" wrap="nowrap">
                    <Badge size="xs" color={t.status === 'RUNNING' ? 'blue' : 'gray'} variant={t.status === 'RUNNING' ? 'filled' : 'light'}>{t.status}</Badge>
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

const CHAT_STORAGE_KEY = 'orchad_chat_history_v1';
const MAX_STORED_MESSAGES = 200;

function loadChatHistory(): ChatMsg[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ChatMsg[]) : [];
  } catch { return []; }
}

function saveChatHistory(msgs: ChatMsg[]): void {
  if (typeof window === 'undefined') return;
  try {
    // Keep only the most recent MAX_STORED_MESSAGES to avoid quota issues
    const slice = msgs.slice(-MAX_STORED_MESSAGES);
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(slice));
  } catch { /* quota exceeded — silently skip */ }
}


// ── Webgen result card ────────────────────────────────────────────────────
function WebgenCard({ content, projectSlug, projectId, onOpenProjects }: { content: string; projectSlug?: string; projectId?: string; onOpenProjects?: () => void }) {
  // Parse business name and pages from the message; projectId comes from structured prop
  const nameMatch = content.match(/Website built successfully!\n\nProject: \*\*([^*]+)\*\*/);
  const pagesMatch = content.match(/Pages: ([^\n]+)/);
  const bizName = nameMatch?.[1] ?? 'Your Website';
  const pages = pagesMatch?.[1] ?? 'index';

  return (
    <Paper
      p={12}
      radius="md"
      style={{
        background: 'linear-gradient(135deg, rgba(26,130,255,0.12) 0%, rgba(0,0,0,0) 100%)',
        border: '1px solid rgba(26,130,255,0.35)',
        marginTop: 4,
      }}
    >
      <Group gap={8} mb={8} wrap="nowrap">
        <ThemeIcon size={28} radius="sm" color="blue" variant="light">
          <IconBolt size={14} />
        </ThemeIcon>
        <div>
          <Text size="sm" fw={700} c="blue.3">Website Built</Text>
          <Text size="xs" c="dimmed">{bizName}</Text>
        </div>
      </Group>
      <Text size="xs" c="dimmed" mb={6}>Pages: {pages}</Text>
      {projectId && (
        <Text size="xs" c="dimmed" ff="monospace" mb={8}
          style={{ opacity: 0.6 }}>ID: {projectId}</Text>
      )}
      <Paper
        component="button"
        p="6px 14px"
        radius="sm"
        style={{
          background: 'rgba(26,130,255,0.18)',
          border: '1px solid rgba(26,130,255,0.4)',
          cursor: 'pointer',
          color: 'var(--mantine-color-blue-3)',
          fontSize: 12,
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
        onClick={() => {
          window.dispatchEvent(new CustomEvent('agentop:open-projects', {
            detail: { projectSlug: projectSlug, projectId: projectId || projectSlug },
          }));
          onOpenProjects?.();
        }}
      >
        <IconCheck size={12} /> Open in Projects
      </Paper>
    </Paper>
  );
}

// ── OpenClaw bridge card ─────────────────────────────────────────────────────
function OpenClawCard({ content }: { content: string }) {
  const channelMatch = content.match(/\b(Discord|Telegram|Slack)\b/i);
  const channel = channelMatch ? channelMatch[1] : 'Multi-channel';
  return (
    <Paper
      p={12}
      radius="md"
      style={{
        background: 'linear-gradient(135deg, rgba(88,101,242,0.12) 0%, rgba(0,0,0,0) 100%)',
        border: '1px solid rgba(88,101,242,0.35)',
        marginTop: 4,
      }}
    >
      <Group gap={8} mb={6} wrap="nowrap">
        <ThemeIcon size={28} radius="sm" color="indigo" variant="light">
          <IconRobot size={14} />
        </ThemeIcon>
        <div>
          <Text size="sm" fw={700} c="indigo.3">OpenClaw Bridge</Text>
          <Text size="xs" c="dimmed">{channel} gateway active</Text>
        </div>
      </Group>
      <Text size="xs" c="dimmed">Message routed through the OpenClaw multi-channel bridge.</Text>
    </Paper>
  );
}

// ── Main component ──────────────────────────────────────────────────────────
export default function OrchestrationHub({ agents, onOpenProjects }: { agents: AgentDefinition[]; onOpenProjects?: () => void }) {
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);

  // Orchad chat state — seeded from server on mount, localStorage as fallback cache
  const [messages, setMessages] = useState<ChatMsg[]>(() => loadChatHistory());
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [cloneUrl, setCloneUrl] = useState('');
  const [showCloneInput, setShowCloneInput] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [startTime, setStartTime] = useState<number | null>(null);
  // Phase label shown before the first REACT_STEP or WEBGEN_PROGRESS arrives
  const [loadingPhase, setLoadingPhase] = useState<string>('understanding request');
  const [webgenStage, setWebgenStage] = useState<string | undefined>(undefined);
  const [contentStage, setContentStage] = useState<string | undefined>(undefined);
  // Abort controller for the in-flight chat request (Stop button)
  const abortControllerRef = useRef<AbortController | null>(null);
  const [lastPublishedJob, setLastPublishedJob] = useState<{ job_id: string; status: string } | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Live reasoning steps per agent (keyed by agent_id)
  const [reactSteps, setReactSteps] = useState<Record<string, { thought: string; tool_calls: string[]; step: number; timestamp: string }>>({});

  // Derived: most recently updated REACT_STEP — used by the live thinking strip.
  // Computed on every render (cheap: tiny object, simple sort).
  const liveStep = loading
    ? ([...Object.entries(reactSteps)]
        .sort(([, a], [, b]) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0] ?? null)
    : null;

  // Model state for Orchad — persisted across sessions
  const [teamPreferences, setTeamPreferences] = useState<Record<string, {
    selected_model?: string | null;
    default_model?: string | null;
    agent_ids: string[];
    resolved_agent_models: Record<string, string>;
    read_only: boolean;
    help_text?: string;
  }>>({});
  const orchadModel = teamPreferences.orchad?.selected_model ?? PERSONAS.orchad.defaultModel;
  const devModel = teamPreferences.dev?.selected_model ?? PERSONAS.dev.defaultModel;
  const socialModel = teamPreferences.social?.selected_model ?? PERSONAS.social.defaultModel;

  // Persist messages to localStorage as a cache whenever they change
  useEffect(() => { saveChatHistory(messages); }, [messages]);

  useEffect(() => {
    api.modelPreferences()
      .then(data => setTeamPreferences(data.teams ?? {}))
      .catch(() => { /* keep defaults on error */ });
  }, []);

  const updateTeamPreference = useCallback((teamId: string, modelId: string) => {
    setTeamPreferences(prev => {
      const existing = prev[teamId];
      if (!existing) return prev;
      const resolvedAgentModels = Object.fromEntries(
        existing.agent_ids.map(agentId => [agentId, modelId])
      );
      return {
        ...prev,
        [teamId]: {
          ...existing,
          selected_model: modelId,
          resolved_agent_models: resolvedAgentModels,
        },
      };
    });
  }, []);

  // ── Hydrate webgen run state from localStorage on mount ──────────────────
  // This ensures stage lights and elapsed timer survive tab changes, route
  // navigation, and page reloads during a running pipeline build.
  // We deliberately DO NOT pre-apply the stale localStorage phase — instead
  // we ask the backend first and only set state if the run is still RUNNING.
  // This prevents the "planning" ghost dots appearing after a completed build.
  useEffect(() => {
    const saved = loadWebgenRun();
    if (saved) {
      // Optionally confirm the run is still active from backend
      api.webgenActiveRun().then(({ run }) => {
        if (!run || run.status !== 'running') {
          // Run no longer active — clear stale state
          clearWebgenRun();
          setWebgenStage(undefined);
          setStartTime(null);
        } else {
          // Use backend started_at as the canonical epoch
          setStartTime(new Date(run.started_at).getTime());
          setWebgenStage(run.current_phase || saved.phase);
        }
      }).catch(() => {
        // Backend unavailable — assume stale, don't show ghost dots
        clearWebgenRun();
        setWebgenStage(undefined);
        setStartTime(null);
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Seed chat history from server on mount ────────────────────────────────
  useEffect(() => {
    api.activeConversation('soul_core').then(data => {
      if (!data.conversation_id) return;
      setConversationId(data.conversation_id);
      if (data.messages && data.messages.length > 0) {
        const serverMsgs: ChatMsg[] = data.messages.map(m => ({
          role: m.role === 'assistant' ? 'agent' : 'user',
          content: m.content,
          agent: m.role === 'assistant' ? m.agent_id : undefined,
          timestamp: m.timestamp,
          selected_model: m.selected_model ?? undefined,
          answering_model: m.answering_model ?? undefined,
          runtime_model: m.runtime_model ?? undefined,
          execution_role: m.execution_role ?? undefined,
          model_source: m.model_source ?? undefined,
          model_used: m.model_used ?? undefined,
          routing_method: m.routing_method ?? undefined,
          ordo_trace: m.ordo_trace ?? undefined,
        }));
        // Only override if server has more history than localStorage
        setMessages(prev => serverMsgs.length > prev.length ? serverMsgs : prev);
      }
    }).catch(() => { /* fallback to localStorage already set */ });
  }, []);

  // ── SSE: subscribe to live REACT_STEP events ──────────────────────────────
  useEffect(() => {
    // Route through the Next proxy so Bearer auth is injected automatically
    const es = new EventSource(`/api/proxy/stream/activity`);
    const handleReactStep = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const agentId = data.agent_id as string;
        if (!agentId) return;
        setReactSteps(prev => ({
          ...prev,
          [agentId]: {
            thought: (data.thought as string) || '',
            tool_calls: (data.tool_calls as string[]) || [],
            step: (data.step as number) || 0,
            timestamp: (data.timestamp as string) || new Date().toISOString(),
          },
        }));
      } catch {}
    };
    es.addEventListener('REACT_STEP', handleReactStep);
    es.addEventListener('WEBGEN_PROGRESS', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        const phase = (data.phase as string) || undefined;
        setWebgenStage(phase);
        // Initialise the start timer on first WEBGEN_PROGRESS if not already set
        setStartTime(prev => prev ?? Date.now());
        // Persist across tab changes / navigation
        setStartTime(prev => {
          if (phase) saveWebgenRun(data.run_id || '', prev ?? Date.now(), phase);
          return prev ?? Date.now();
        });
        setReactSteps(prev => ({
          ...prev,
          webgen: {
            thought: `${data.phase}${data.detail ? ` — ${data.detail}` : ''}`,
            tool_calls: [],
            step: (data.step as number) || 1,
            timestamp: (data.timestamp as string) || new Date().toISOString(),
          },
        }));
      } catch {}
    });
    es.addEventListener('WEBGEN_COMPLETE', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        clearWebgenRun();
        if (data.status === 'success') {
          const previewUrl = `/preview/${data.project_slug}/index.html`;
          const resultContent = `Website built successfully!\n\nProject: **${data.business_name || 'Site'}**\n`
            + (data.clone_url ? `Cloned from: ${data.clone_url}\n` : '')
            + `Pages: ${(data.pages || []).join(', ') || 'index'}\n`
            + `Project ID: \`${data.project_id}\`\n`
            + `Preview: ${previewUrl}`;
          setMessages(p => [...p, {
            role: 'agent',
            content: resultContent,
            agent: 'webgen',
            timestamp: data.timestamp || new Date().toISOString(),
            run_id: data.run_id || undefined,
            webgen_project_slug: data.project_slug || undefined,
            webgen_project_id: data.project_id || undefined,
          }]);
          window.dispatchEvent(new CustomEvent('agentop:webgen-complete'));
          // Do not auto-navigate — user stays in chat to see the result message
        } else {
          setMessages(p => [...p, {
            role: 'agent',
            content: `Website build failed: ${data.error || 'Unknown error'}`,
            agent: 'webgen',
            timestamp: data.timestamp || new Date().toISOString(),
            error_meta: { status: 500 },
          }]);
        }
        setWebgenStage(undefined);
        setLoading(false);
        setStartTime(null);
        poll();
      } catch {}
    });
    es.addEventListener('pipeline_stage', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.pipeline === 'content') {
          const raw = (data.stage as string) || '';
          // Stage events now carry semantics: "script:started", "script:completed", "script:failed"
          // Older events without suffix are treated as "started" for backwards compat.
          if (raw.endsWith(':failed') || raw.endsWith(':completed')) {
            // A failed or completed stage clears the active dot; do not carry stale state
            setContentStage(undefined);
          } else {
            // Strip ":started" suffix so stage IDs match PERSONAS stage keys
            const stageId = raw.replace(/:started$/, '') || undefined;
            setContentStage(stageId as string | undefined);
          }
        }
      } catch {}
    });
    es.addEventListener('CONTENT_PIPELINE_COMPLETE', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setContentStage(undefined);
        if (data.job_id) {
          setLastPublishedJob({ job_id: data.job_id, status: data.status ?? 'success' });
        }
      } catch {
        setContentStage(undefined);
      }
    });
    return () => { es.removeEventListener('REACT_STEP', handleReactStep); es.close(); };
  }, []);

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
  }, [poll]);
  useAdaptivePolling({
    intervalMs: 10000,
    onTick: poll,
  });

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    if (!startTime) { setElapsed(0); return; }
    const iv = setInterval(() => {
      const s = Math.round((Date.now() - startTime) / 1000);
      setElapsed(s);
      // Advance the pre-step phase label if no REACT_STEP has arrived yet
      if (!liveStep) {
        if (s < 3) setLoadingPhase('understanding request');
        else if (s < 8) setLoadingPhase('selecting route');
        else if (s < 15) setLoadingPhase('preparing execution');
        else setLoadingPhase('waiting for first reasoning step');
      }
    }, 1000);
    return () => clearInterval(iv);
  }, [startTime, liveStep]);

  // ── Direct send (used by quick-reply chips) ──────────────────────────────
  const sendDirect = async (msg: string) => {
    if (!msg || loading) return;
    setMessages(p => [...p, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;
    setLoading(true);
    setStartTime(Date.now());
    setLoadingPhase('understanding request');
    setReactSteps({});
    setWebgenStage(undefined);
    setContentStage(undefined);
    try {
      const res = await api.chat(PERSONAS.orchad.chatAgent, msg, undefined, conversationId ?? undefined, ctrl.signal);
      if (res.conversation_id) setConversationId(res.conversation_id);
      setMessages(p => [...p, {
        role: 'agent', content: res.message, agent: res.agent_id,
        timestamp: new Date().toISOString(),
        ordo_trace: res.ordo_trace,
        sources: (res as any).sources ?? undefined,
        selected_model: res.selected_model,
        answering_model: res.answering_model,
        runtime_model: res.runtime_model,
        execution_role: res.execution_role,
        model_source: res.model_source,
        routing_method: res.routing_method,
        model_used: res.model_used,
        drift_status: res.drift_status,
        run_id: (res as any).run_id ?? undefined,
      }]);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User hit Stop — don't show error message
      } else {
        const elapsedAtFail = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;
        setMessages(p => [...p, {
          role: 'agent',
          content: err instanceof Error ? err.message : 'Request failed',
          timestamp: new Date().toISOString(),
          error_meta: { elapsed_s: elapsedAtFail },
        }]);
      }
    } finally {
      abortControllerRef.current = null;
      setLoading(false);
      setStartTime(null);
      setWebgenStage(undefined);
      setContentStage(undefined);
      poll();
    }
  };

  // ── Send message ──────────────────────────────────────────────────────────
  const send = async (e: FormEvent) => {
    e.preventDefault();
    const msg = input.trim();
    const urlToBuild = cloneUrl.trim();

    // ── Clone URL path: route through /chat so Ordo owns the lifecycle ─────
    // The backend's webgen-intent regex detects clone+URL and starts the
    // pipeline as an async background task, returning immediately.
    // WEBGEN_PROGRESS SSE events animate the dots; WEBGEN_COMPLETE renders
    // the final result card.
    if (urlToBuild) {
      if (!urlToBuild.startsWith('http')) return;
      const userMsg = msg ? `Clone this site and ${msg}\n${urlToBuild}` : `Clone this site and rebuild it\n${urlToBuild}`;
      setInput('');
      setCloneUrl('');
      setShowCloneInput(false);
      setMessages(p => [...p, { role: 'user', content: userMsg, timestamp: new Date().toISOString() }]);
      const ctrl = new AbortController();
      abortControllerRef.current = ctrl;
      setLoading(true);
      setStartTime(Date.now());
      setLoadingPhase('routing clone request');
      setReactSteps({});
      setWebgenStage(undefined);
      setContentStage(undefined);
      let _webgenBg = false;
      try {
        const res = await api.chat(PERSONAS.orchad.chatAgent, userMsg, undefined, conversationId ?? undefined, ctrl.signal);
        if (res.conversation_id) setConversationId(res.conversation_id);
        setMessages(p => [...p, {
          role: 'agent', content: res.message, agent: res.agent_id,
          timestamp: new Date().toISOString(),
          ordo_trace: res.ordo_trace,
          selected_model: res.selected_model,
          answering_model: res.answering_model,
          runtime_model: res.runtime_model,
          execution_role: res.execution_role,
          model_source: res.model_source,
          routing_method: res.routing_method,
          model_used: res.model_used,
          drift_status: res.drift_status,
        }]);
        // If the backend started the webgen pipeline in background,
        // keep loading=true — WEBGEN_COMPLETE SSE will clear it.
        if (res.agent_id === 'webgen') {
          _webgenBg = true;
          setWebgenStage('clone_recon');
          // Don't clear loading — SSE WEBGEN_COMPLETE handles that
          return;
        }
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') {
          // User hit Stop
        } else {
          const detail = err instanceof ApiError ? (err.detail ?? `HTTP ${err.status}`) : err instanceof Error ? err.message : 'Clone failed';
          setMessages(p => [...p, {
            role: 'agent',
            content: typeof detail === 'string' ? detail : 'Clone failed',
            timestamp: new Date().toISOString(),
            error_meta: { elapsed_s: startTime ? Math.round((Date.now() - startTime) / 1000) : 0 },
          }]);
        }
      } finally {
        abortControllerRef.current = null;
        // Only clear loading/timer if NOT a webgen background task
        if (!_webgenBg) {
          setLoading(false);
          setStartTime(null);
          setWebgenStage(undefined);
          setContentStage(undefined);
        }
        poll();
      }
      return;
    }

    // ── Normal chat path ───────────────────────────────────────────────────
    if (!msg || loading) return;
    setInput('');
    setMessages(p => [...p, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;
    setLoading(true);
    setStartTime(Date.now());
    setLoadingPhase('understanding request');
    // Clear live steps so phase label shows from scratch
    setReactSteps({});
    setWebgenStage(undefined);
    setContentStage(undefined);
    let _normalWebgenBg = false;
    try {
      const res = await api.chat(PERSONAS.orchad.chatAgent, msg, undefined, conversationId ?? undefined, ctrl.signal);
      // Keep conversation_id for continuity
      if (res.conversation_id) setConversationId(res.conversation_id);
      setMessages(p => [...p, {
        role: 'agent', content: res.message, agent: res.agent_id,
        timestamp: new Date().toISOString(),
        ordo_trace: res.ordo_trace,
        sources: (res as any).sources ?? undefined,
        selected_model: res.selected_model,
        answering_model: res.answering_model,
        runtime_model: res.runtime_model,
        execution_role: res.execution_role,
        model_source: res.model_source,
        routing_method: res.routing_method,
        model_used: res.model_used,
        drift_status: res.drift_status,
        run_id: (res as any).run_id ?? undefined,
      }]);
      // If webgen pipeline ran, notify the Projects tab to refresh (but do NOT
      // auto-navigate away — the user is still in chat and will see the result here)
      if (res.agent_id === 'webgen') {
        _normalWebgenBg = true;
        window.dispatchEvent(new CustomEvent('agentop:webgen-complete'));
        // Removed: agentop:open-projects — tab switch should only happen on explicit user action
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User hit Stop — no error message
      } else {
        const elapsedAtFail = startTime ? Math.round((Date.now() - startTime) / 1000) : 0;
        const lastStepEntry = [...Object.entries(reactSteps)]
          .sort(([, a], [, b]) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0];
        const lastLiveStep = lastStepEntry ? `step ${lastStepEntry[1].step}: ${lastStepEntry[1].thought.slice(0, 80)}` : undefined;

        let errorContent = 'Request failed';
        const errorMeta: NonNullable<ChatMsg['error_meta']> = { elapsed_s: elapsedAtFail, selected_model: orchadModel };

        if (err instanceof ApiError) {
          errorMeta.status = err.status;
          errorMeta.request_id = err.requestId;
          const detail = err.detail || err.payload?.raw;
          errorContent = typeof detail === 'string' ? detail : `HTTP ${err.status} error`;
          if (lastLiveStep) errorMeta.last_live_step = lastLiveStep;
        } else if (err instanceof Error) {
          errorContent = err.message;
          if (lastLiveStep) errorMeta.last_live_step = lastLiveStep;
        }

        setMessages(p => [...p, {
          role: 'agent',
          content: errorContent,
          timestamp: new Date().toISOString(),
          error_meta: errorMeta,
        }]);
      }
    } finally {
      abortControllerRef.current = null;
      if (!_normalWebgenBg) {
        setLoading(false);
        setStartTime(null);
        setWebgenStage(undefined);
        setContentStage(undefined);
      }
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
            <ModelSwitcher teamId="orchad" value={orchadModel} onChange={modelId => updateTeamPreference('orchad', modelId)} />
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
            <Stack gap={0} style={{ minHeight: 560, display: 'flex', flexDirection: 'column' }}>
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
                          maxWidth: '88%',
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
                        {/* ── Quick-reply chips — shown when agent surfaces numbered suggestions ── */}
                        {m.role === 'agent' && /reply with a number \(1[–-]5\)/i.test(m.content) && !loading && (
                          <Group gap={4} mt={8} wrap="nowrap">
                            {[1, 2, 3, 4, 5].map(n => (
                              <Paper
                                key={n}
                                component="button"
                                p="4px 10px"
                                radius="sm"
                                style={{
                                  cursor: 'pointer',
                                  background: 'rgba(26,130,255,0.12)',
                                  border: '1px solid rgba(26,130,255,0.35)',
                                  color: 'var(--mantine-color-blue-3)',
                                  fontSize: 12,
                                  fontWeight: 600,
                                  lineHeight: 1.6,
                                }}
                                onClick={() => sendDirect(String(n))}
                              >
                                {n}
                              </Paper>
                            ))}
                          </Group>
                        )}
                        {/* ── Preview URL button — shown for any agent message containing a /preview/ path ── */}
                        {m.role === 'agent' && (() => {
                          const previewMatch = m.content.match(/\/preview\/([^\s\n"']+\/index\.html)/);
                          if (!previewMatch) return null;
                          const previewPath = `/preview/${previewMatch[1]}`;
                          return (
                            <Paper
                              component="a"
                              href={previewPath}
                              target="_blank"
                              rel="noopener noreferrer"
                              p="6px 14px"
                              radius="sm"
                              mt={8}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 6,
                                background: 'rgba(26,130,255,0.18)',
                                border: '1px solid rgba(26,130,255,0.4)',
                                color: 'var(--mantine-color-blue-3)',
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: 'pointer',
                                textDecoration: 'none',
                              }}
                            >
                              <IconExternalLink size={12} /> Open Site
                            </Paper>
                          );
                        })()}
                        {m.role === 'agent' && m.agent === 'webgen' && (m.webgen_project_slug || m.webgen_project_id) && (
                          <WebgenCard content={m.content} projectSlug={m.webgen_project_slug} projectId={m.webgen_project_id} onOpenProjects={onOpenProjects} />
                        )}
                        {m.role === 'agent' && m.routing_method === 'openclaw' && (
                          <OpenClawCard content={m.content} />
                        )}
                        {m.role === 'agent' && m.agent && (
                          <HandoffDots agentId={m.agent} webgenStage={m.agent === 'webgen' ? webgenStage : undefined} />
                        )}
                        {m.role === 'agent' && m.ordo_trace && (
                          <OrdoPanel
                            trace={m.ordo_trace}
                            selectedModel={m.selected_model}
                            answeringModel={m.answering_model ?? m.model_used}
                            runtimeModel={m.runtime_model}
                            executionRole={m.execution_role}
                            modelSource={m.model_source}
                          />
                        )}
                        {m.role === 'agent' && <RoutingPills routingMethod={m.routing_method} />}
                        {/* ── Content pipeline post link — shown when the pipeline completes ── */}
                        {m.role === 'agent' && m.routing_method === 'content_intent' && m.run_id && lastPublishedJob?.job_id === m.run_id && (
                          <Paper
                            component="a"
                            href={`${typeof window !== 'undefined' ? window.location.origin.replace('3007', '8000') : 'http://127.0.0.1:8000'}/content/jobs/${m.run_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            mt={6}
                            p={6}
                            radius="sm"
                            style={{
                              display: 'block',
                              cursor: 'pointer',
                              background: lastPublishedJob.status === 'success' ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                              border: `1px solid ${lastPublishedJob.status === 'success' ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                              textDecoration: 'none',
                            }}
                          >
                            <Group gap={6} wrap="nowrap">
                              <IconExternalLink size={12} style={{ color: lastPublishedJob.status === 'success' ? '#22c55e' : '#ef4444', flexShrink: 0 }} />
                              <Text size="xs" style={{ color: lastPublishedJob.status === 'success' ? '#22c55e' : '#ef4444' }}>
                                {lastPublishedJob.status === 'success' ? 'View published package' : 'Pipeline failed — view job'}
                              </Text>
                            </Group>
                          </Paper>
                        )}
                        {m.role === 'agent' && m.sources && m.sources.length > 0 && (
                          <Box mt={4} style={{ borderTop: '1px solid var(--mantine-color-dark-5)', paddingTop: 4 }}>
                            <Group gap={4} wrap="nowrap">
                              <IconBook size={10} style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }} />
                              <Text size="xs" c="dimmed">
                                Sources: {m.sources.slice(0, 4).map((s, i) => (
                                  <Text key={i} component="span" size="xs" ff="monospace" c="blue.4">{s}{i < Math.min(m.sources!.length, 4) - 1 ? ', ' : ''}</Text>
                                ))}
                              </Text>
                            </Group>
                          </Box>
                        )}
                        {m.role === 'agent' && m.error_meta && (
                          <Box
                            mt={6}
                            p={6}
                            style={{
                              borderTop: '1px solid rgba(239,68,68,0.3)',
                              background: 'rgba(239,68,68,0.06)',
                              borderRadius: 4,
                            }}
                          >
                            <Group gap={4} mb={4} wrap="nowrap">
                              <Text size="xs" fw={600} c="red.4">Debug context</Text>
                              {m.error_meta.status && (
                                <Badge size="xs" color="red" variant="light">HTTP {m.error_meta.status}</Badge>
                              )}
                              {m.error_meta.elapsed_s !== undefined && (
                                <Badge size="xs" color="gray" variant="light">{m.error_meta.elapsed_s}s</Badge>
                              )}
                            </Group>
                            {m.error_meta.request_id && (
                              <Text size="xs" c="dimmed" ff="monospace">ref: {m.error_meta.request_id}</Text>
                            )}
                            {m.error_meta.selected_model && (
                              <Text size="xs" c="dimmed">model: {m.error_meta.selected_model}</Text>
                            )}
                            {m.error_meta.last_live_step && (
                              <Text size="xs" c="dimmed" mt={2}>last step: {m.error_meta.last_live_step}</Text>
                            )}
                          </Box>
                        )}
                        {m.role === 'agent' && (m.routing_method || m.answering_model || m.model_used || (m.drift_status && m.drift_status !== 'GREEN')) && (
                          <Group gap={4} mt={4} wrap="nowrap">
                            {m.routing_method && (
                              <Badge size="xs" variant="outline" color="gray">{m.routing_method}</Badge>
                            )}
                            {(m.answering_model || m.model_used) && (
                              <Tooltip
                                label={buildModelMetaTooltip({
                                  selected_model: m.selected_model,
                                  answering_model: m.answering_model ?? m.model_used,
                                  runtime_model: m.runtime_model,
                                  execution_role: m.execution_role,
                                  model_source: m.model_source,
                                })}
                                multiline
                                maw={320}
                              >
                                <Badge size="xs" variant="dot" color="violet">
                                  {formatModelLabel(m.answering_model ?? m.model_used)}
                                </Badge>
                              </Tooltip>
                            )}
                            {m.drift_status && m.drift_status !== 'GREEN' && (
                              <Badge size="xs" color={m.drift_status === 'RED' ? 'red' : 'yellow'} variant="light">{m.drift_status}</Badge>
                            )}
                          </Group>
                        )}
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
                      <Paper
                        p="xs"
                        radius="md"
                        style={{
                          background: 'var(--mantine-color-dark-7)',
                          border: '1px solid var(--mantine-color-dark-5)',
                          maxWidth: '88%',
                          minWidth: 180,
                        }}
                      >
                        {liveStep ? (
                          <Stack gap={4}>
                            {/* Header row: loader + step number + agent badge + elapsed */}
                            <Group gap={6} wrap="nowrap" align="center">
                              <Loader size="xs" color="blue" />
                              <Text size="xs" c="dimmed" ff="monospace" fw={600}>
                                Step {liveStep[1].step}
                              </Text>
                              {liveStep[0] && liveStep[0] !== 'auto' && (
                                <Badge size="xs" variant="dot" color="blue" style={{ flexShrink: 0 }}>
                                  {liveStep[0].replace(/_agent$/, '').replace(/_/g, ' ')}
                                </Badge>
                              )}
                              <Text size="xs" c="dimmed" style={{ marginLeft: 'auto', opacity: 0.5 }}>
                                {elapsed}s
                              </Text>
                            </Group>
                            {/* Thought preview — truncated, italic */}
                            {liveStep[1].thought.length > 0 && (
                              <Text
                                size="xs"
                                c="dimmed"
                                style={{ fontStyle: 'italic', lineHeight: 1.4, opacity: 0.85 }}
                              >
                                &ldquo;{liveStep[1].thought.length > 110
                                  ? liveStep[1].thought.slice(0, 110) + '…'
                                  : liveStep[1].thought}&rdquo;
                              </Text>
                            )}
                            {/* Tool chips — shown when a tool call is in progress */}
                            {liveStep[1].tool_calls.length > 0 && (
                              <Group gap={4} mt={2}>
                                {liveStep[1].tool_calls.slice(0, 3).map(t => (
                                  <Badge key={t} size="xs" color="teal" variant="light">
                                    {t}
                                  </Badge>
                                ))}
                              </Group>
                            )}
                          </Stack>
                        ) : (
                          /* No REACT_STEP yet — show progressive phase label */
                          <Group gap={6} align="center">
                            <Loader size="xs" color="blue" />
                            <Text size="xs" c="dimmed">{loadingPhase}</Text>
                            <Text size="xs" c="dimmed" ff="monospace" style={{ opacity: 0.5 }}>{elapsed}s</Text>
                          </Group>
                        )}
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
                  {showCloneInput && (
                    <Group gap={6} wrap="nowrap" align="center" mb={6} pb={6}
                      style={{ borderBottom: '1px solid var(--mantine-color-dark-5)' }}
                    >
                      <IconLink size={12} style={{ color: 'var(--mantine-color-dimmed)', flexShrink: 0 }} />
                      <input
                        type="url"
                        placeholder="https://example.com — paste site to clone"
                        value={cloneUrl}
                        onChange={e => setCloneUrl(e.target.value)}
                        style={{
                          flex: 1, background: 'transparent', border: 'none', outline: 'none',
                          color: 'var(--mantine-color-blue-3)', fontSize: 12, fontFamily: 'monospace',
                        }}
                      />
                      {cloneUrl && (
                        <ActionIcon size="xs" variant="transparent" color="gray" onClick={() => setCloneUrl('')}>
                          <IconX size={10} />
                        </ActionIcon>
                      )}
                    </Group>
                  )}
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
                      <Paper
                        p={4}
                        radius="sm"
                        style={{ cursor: 'pointer', background: showCloneInput ? `${PERSONAS.orchad.color}30` : 'transparent' }}
                        title="Clone a website URL"
                        onClick={() => setShowCloneInput(o => !o)}
                      >
                        <IconLink size={14} color={showCloneInput ? PERSONAS.orchad.color : 'var(--mantine-color-dimmed)'} />
                      </Paper>
                      {messages.length > 0 && (
                        <Paper
                          p={4}
                          radius="sm"
                          style={{ cursor: 'pointer', background: 'transparent' }}
                          title="Clear chat history"
                          onClick={() => {
                            setMessages([]);
                            setConversationId(null);
                            try { localStorage.removeItem('orchad_chat_history_v1'); } catch { /* ignore */ }
                          }}
                        >
                          <IconX size={14} color="var(--mantine-color-dimmed)" />
                        </Paper>
                      )}
                      {loading && (
                        <Paper
                          p={6}
                          radius="sm"
                          style={{ cursor: 'pointer', background: '#c0392b', border: 'none' }}
                          title="Stop request"
                          onClick={() => {
                            abortControllerRef.current?.abort();
                            abortControllerRef.current = null;
                            setLoading(false);
                            setStartTime(null);
                          }}
                        >
                          <IconPlayerStop size={14} color="white" />
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
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <DevTeamCard
            agentStates={agentStates}
            tasks={tasks}
            agents={agents}
            reactSteps={reactSteps}
            webgenStage={webgenStage}
            elapsed={elapsed}
            model={devModel}
            onModelChange={modelId => updateTeamPreference('dev', modelId)}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <SocialTeamCard
            agentStates={agentStates}
            tasks={tasks}
            reactSteps={reactSteps}
            contentStage={contentStage}
            model={socialModel}
            onModelChange={modelId => updateTeamPreference('social', modelId)}
          />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <OpsTeamCard agentStates={agentStates} tasks={tasks} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <OpenClawStatusCard />
        </Grid.Col>
      </Grid>
    </Stack>
  );
}
