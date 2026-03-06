/**
 * Agentop Dashboard — Main Page (v3 — Mantine UI)
 *
 * Tabbed navigation:
 *   Overview | Agents | Chat | Projects | Token Usage | System
 *
 * Built with Mantine v7 component library.
 * READ-ONLY (INV-8): The dashboard cannot mutate backend state
 * except through /chat, /soul/reflect, and /soul/goals endpoints.
 */
'use client';

import { useEffect, useState, useCallback, useRef, FormEvent } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import {
  AppShell,
  Badge,
  Box,
  Button,
  Card,
  Code,
  Container,
  Divider,
  Flex,
  Grid,
  Group,
  Indicator,
  Loader,
  Paper,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
  UnstyledButton,
  rem,
} from '@mantine/core';
import {
  IconActivity,
  IconBolt,
  IconBrain,
  IconChartBar,
  IconCheck,
  IconChevronLeft,
  IconClock,
  IconCloud,
  IconCode,
  IconCpu,
  IconDatabase,
  IconFileText,
  IconFolder,
  IconFolderOpen,
  IconHexagon,
  IconLayout,
  IconMessage,
  IconPlayerPlay,
  IconRefresh,
  IconRobot,
  IconSearch,
  IconSend,
  IconServer,
  IconSettings,
  IconShield,
  IconTargetArrow,
  IconTools,
  IconX,
} from '@tabler/icons-react';

import {
  api,
  type AgentDefinition,
  type AgentState,
  type AgentMemoryUsage,
  type DriftReport,
  type ToolLog,
  type ToolDefinition,
  type HealthCheck,
  type SoulGoal,
  type SoulReflection,
  type TaskItem,
  type TaskStats,
  type FolderEntry,
  type FolderAnalysis,
  type LLMStats,
  type LLMCapacity,
  type ModelCapacity,
  type ProjectEntry,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const POLL_INTERVAL = 5000;

const DashboardLayout = dynamic(() => import('@/components/DashboardLayout'), {
  ssr: false,
});

const OrchestrationHub = dynamic(() => import('@/components/OrchestrationHub'), {
  ssr: false,
});

const TIER_LABELS: Record<number, string> = {
  0: 'Tier 0 — Soul',
  1: 'Tier 1 — Cluster Ops',
  2: 'Tier 2 — Intelligence',
  3: 'Tier 3 — Interface',
};

const AGENT_TIER: Record<string, number> = {
  soul_core: 0,
  devops_agent: 1, monitor_agent: 1, self_healer_agent: 1,
  code_review_agent: 2, security_agent: 2, data_agent: 2,
  prompt_engineer: 2, token_optimizer: 2, curriculum_advisor: 2,
  vocabulary_coach: 2, career_intel: 2, accreditation_advisor: 2,
  pedagogy_agent: 2, comms_agent: 3, cs_agent: 3, it_agent: 3,
  knowledge_agent: 3,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function impactColor(level: string): string {
  switch (level) {
    case 'CRITICAL': return 'red';
    case 'HIGH': return 'orange';
    case 'MEDIUM': return 'yellow';
    case 'LOW': return 'green';
    default: return 'blue';
  }
}

function driftColor(s: string): string {
  switch (s) {
    case 'GREEN': return 'green';
    case 'YELLOW': return 'yellow';
    case 'RED': return 'red';
    default: return 'gray';
  }
}

function projectTypeInfo(type: string): { label: string; color: string } {
  switch (type) {
    case 'webgen': return { label: 'Website', color: 'blue' };
    case 'content': return { label: 'Content', color: 'orange' };
    case 'webgen_project': return { label: 'WebGen Project', color: 'yellow' };
    default: return { label: type, color: 'gray' };
  }
}

const fmt = {
  num: (n: number) => n.toLocaleString(),
  mb: (bytes: number) => `${(bytes / (1024 * 1024)).toFixed(2)} MB`,
  time: (ts: string) => { try { return new Date(ts).toLocaleTimeString(); } catch { return ts; } },
  date: (ts: string) => { try { return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); } catch { return ts; } },
  size: (b: number) => b > 1024 * 1024 ? `${(b / (1024 * 1024)).toFixed(1)} MB` : b > 1024 ? `${(b / 1024).toFixed(1)} KB` : `${b} B`,
};

// ---------------------------------------------------------------------------
// Stat card component
// ---------------------------------------------------------------------------
function StatCard({ label, value, color, onClick }: { label: string; value: string | number; color?: string; onClick?: () => void }) {
  return (
    <Card shadow="sm" padding="lg" withBorder style={{ cursor: onClick ? 'pointer' : undefined }} onClick={onClick}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      <Text size={rem(28)} fw={700} ff="monospace" c={color} mt={4}>{value}</Text>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard Page
// ---------------------------------------------------------------------------
export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<string | null>('overview');
  const [osView, setOsView] = useState(false);

  // Core state
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [logs, setLogs] = useState<ToolLog[]>([]);
  const [memoryUsage, setMemoryUsage] = useState<AgentMemoryUsage[]>([]);
  const [soulGoals, setSoulGoals] = useState<SoulGoal[]>([]);
  const [lastReflection, setLastReflection] = useState<SoulReflection | null>(null);
  const [reflecting, setReflecting] = useState(false);
  const [newGoalTitle, setNewGoalTitle] = useState('');
  const [newGoalDesc, setNewGoalDesc] = useState('');
  const [addingGoal, setAddingGoal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  // Chat state
  const [chatAgent, setChatAgent] = useState('knowledge_agent');
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<
    { role: 'user' | 'agent'; content: string; agent?: string; drift?: string; timestamp?: string }[]
  >([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatStartTime, setChatStartTime] = useState<number | null>(null);
  const [chatElapsed, setChatElapsed] = useState(0);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Task state
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [taskStats, setTaskStats] = useState<TaskStats>({ total: 0, queued: 0, running: 0, completed: 0, failed: 0 });

  // SSE state
  const [liveEvents, setLiveEvents] = useState<{ type: string; data: Record<string, unknown>; timestamp: string }[]>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const liveEndRef = useRef<HTMLDivElement>(null);

  // Folder state
  const [folderEntries, setFolderEntries] = useState<FolderEntry[]>([]);
  const [folderCurrent, setFolderCurrent] = useState('.');
  const [folderParent, setFolderParent] = useState<string | null>(null);
  const [folderAnalysis, setFolderAnalysis] = useState<FolderAnalysis | null>(null);
  const [folderAgentResponse, setFolderAgentResponse] = useState<string | null>(null);
  const [analyzingFolder, setAnalyzingFolder] = useState(false);
  const [browsingFolder, setBrowsingFolder] = useState(false);

  // LLM state
  const [llmStats, setLlmStats] = useState<LLMStats | null>(null);
  const [llmCapacity, setLlmCapacity] = useState<LLMCapacity | null>(null);

  // Projects state
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [projectTypes, setProjectTypes] = useState<Record<string, number>>({});
  const [projectFilter, setProjectFilter] = useState('all');
  const [selectedProject, setSelectedProject] = useState<ProjectEntry | null>(null);
  const [projectFiles, setProjectFiles] = useState<{ name: string; path: string; size_bytes: number; extension: string }[]>([]);

  // Agent detail
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // ── Data fetching ──────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      const [h, a, t, d, l, mem, goals] = await Promise.all([
        api.health(),
        api.agents(),
        api.tools(),
        api.drift(),
        api.logs(30),
        api.memoryAgents().catch(() => ({ agents: [], total_size_bytes: 0, total_size_mb: 0 })),
        api.soulGoals().catch(() => ({ goals: [], count: 0 })),
      ]);
      setHealth(h); setAgents(a); setTools(t); setDrift(d); setLogs(l);
      setMemoryUsage(mem?.agents ?? []); setSoulGoals(goals?.goals ?? []);
      setConnected(true); setError(null);

      try { const td = await api.tasks(30); setTasks(td.tasks); setTaskStats(td.stats); } catch {}
      try { const st = await api.status(); setAgentStates(st.agents); } catch {}
      try { setLlmStats(await api.llmStats()); } catch {}
      try { setLlmCapacity(await api.llmCapacity()); } catch {}
      try { const p = await api.projects(); setProjects(p.projects); setProjectTypes(p.types); } catch {}

      if (a.length > 0 && !a.some((ag) => ag.agent_id === chatAgent)) setChatAgent(a[0].agent_id);
    } catch (e) {
      setConnected(false);
      setError(`Backend unreachable: ${e instanceof Error ? e.message : 'Unknown error'}`);
    }
  }, [chatAgent]);

  useEffect(() => { fetchData(); const i = setInterval(fetchData, POLL_INTERVAL); return () => clearInterval(i); }, [fetchData]);

  // ── Soul actions ───────────────────────────────────────────────────────
  const triggerReflection = async () => {
    if (reflecting) return;
    setReflecting(true);
    try { setLastReflection(await api.soulReflect('dashboard')); } catch {} finally { setReflecting(false); }
  };

  const submitGoal = async (e: FormEvent) => {
    e.preventDefault();
    if (!newGoalTitle.trim() || addingGoal) return;
    setAddingGoal(true);
    try {
      await api.soulAddGoal(newGoalTitle.trim(), newGoalDesc.trim());
      setNewGoalTitle(''); setNewGoalDesc('');
      const g = await api.soulGoals(); setSoulGoals(g.goals);
    } catch {} finally { setAddingGoal(false); }
  };

  // ── Chat ───────────────────────────────────────────────────────────────
  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || !chatAgent || chatLoading) return;
    const msg = chatInput.trim();
    setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: msg, timestamp: new Date().toISOString() }]);
    setChatLoading(true); setChatStartTime(Date.now());
    try {
      const res = await api.chat(chatAgent, msg);
      setChatMessages(prev => [...prev, { role: 'agent', content: res.message, agent: res.agent_id, drift: res.drift_status, timestamp: new Date().toISOString() }]);
    } catch (e) {
      setChatMessages(prev => [...prev, { role: 'agent', content: `Error: ${e instanceof Error ? e.message : 'Unknown'}`, timestamp: new Date().toISOString() }]);
    } finally { setChatLoading(false); setChatStartTime(null); fetchData(); }
  };

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);
  useEffect(() => {
    if (!chatStartTime) { setChatElapsed(0); return; }
    const i = setInterval(() => setChatElapsed(Math.round((Date.now() - chatStartTime) / 1000)), 500);
    return () => clearInterval(i);
  }, [chatStartTime]);

  // ── SSE ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!connected) return;
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const es = new EventSource(`${API_BASE}/stream/activity`);
    es.addEventListener('connected', () => setSseConnected(true));
    const handleEvent = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setLiveEvents(prev => [...prev.slice(-99), { type: e.type, data, timestamp: data.timestamp || new Date().toISOString() }]);
      } catch {}
    };
    ['task_created','task_started','task_completed','task_failed','tool_start','tool_end','llm_response','agent_active','agent_idle'].forEach(t => es.addEventListener(t, handleEvent));
    es.onerror = () => setSseConnected(false);
    return () => { es.close(); setSseConnected(false); };
  }, [connected]);
  useEffect(() => { liveEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [liveEvents]);

  // ── Folder browsing ────────────────────────────────────────────────────
  const browseTo = async (path: string) => {
    setBrowsingFolder(true);
    try { const r = await api.browseFolders(path); setFolderEntries(r.entries); setFolderCurrent(r.current); setFolderParent(r.parent); } catch {} finally { setBrowsingFolder(false); }
  };
  const analyzeCurrentFolder = async () => {
    if (analyzingFolder) return;
    setAnalyzingFolder(true); setFolderAnalysis(null); setFolderAgentResponse(null);
    try { const r = await api.analyzeFolder(folderCurrent, 'code_review_agent', 200); setFolderAnalysis(r.analysis); if (r.agent_response) setFolderAgentResponse(r.agent_response); } catch {} finally { setAnalyzingFolder(false); }
  };
  useEffect(() => { if (connected) browseTo('.'); }, [connected]);

  // ── Project detail ─────────────────────────────────────────────────────
  const loadProjectFiles = async (proj: ProjectEntry) => {
    setSelectedProject(proj); setProjectFiles([]);
    try { const r = await api.projectFiles(proj.id, proj.type); setProjectFiles(r.files); } catch {}
  };

  // ── Helpers ────────────────────────────────────────────────────────────
  const getAgentState = (id: string) => agentStates.find(s => s.agent_id === id);
  const driftStatus = drift?.status || 'GREEN';
  const agentsByTier = agents.reduce<Record<number, AgentDefinition[]>>((acc, ag) => {
    const tier = AGENT_TIER[ag.agent_id] ?? 3;
    (acc[tier] = acc[tier] || []).push(ag);
    return acc;
  }, {});
  const filteredProjects = projectFilter === 'all' ? projects : projects.filter(p => p.type === projectFilter);

  // ======================================================================
  // RENDER
  // ======================================================================
  if (osView) return (
    <div style={{ position: 'relative' }}>
      <Button
        size="xs"
        variant="default"
        style={{ position: 'fixed', top: 10, right: 10, zIndex: 1000, opacity: 0.7 }}
        onClick={() => setOsView(false)}
      >
        ← Classic
      </Button>
      <DashboardLayout />
    </div>
  );

  return (
    <AppShell padding="md">
      <AppShell.Main>
        <Container size="xl" px="md">
          {/* ── Header ──────────────────────────────────────────────── */}
          <Group justify="space-between" mb="lg" pb="md" style={{ borderBottom: '1px solid var(--mantine-color-dark-4)' }}>
            <div>
              <Title order={2} fw={700}>Agentop Control Center</Title>
              <Text size="xs" c="dimmed">Local-first multi-agent system · soul-driven · drift governed</Text>
            </div>
            <Group gap="md">
              {health && (
                <>
                  <Badge variant="dot" color={health.llm_available ? 'green' : 'red'} size="lg">
                    LLM: {health.llm_available ? 'Connected' : 'Offline'}
                  </Badge>
                  <Text size="xs" c="dimmed" ff="monospace">Uptime: {Math.round(health.uptime_seconds)}s</Text>
                </>
              )}
              <Button size="xs" variant="light" onClick={() => setOsView(true)}>OS View</Button>
              <Badge variant="filled" color={driftColor(driftStatus)} size="lg" leftSection={
                <Box w={8} h={8} style={{ borderRadius: '50%', background: 'currentColor', animation: 'pulse 2s ease-in-out infinite' }} />
              }>
                Drift: {driftStatus}
              </Badge>
            </Group>
          </Group>

          {error && (
            <Paper p="sm" mb="md" withBorder style={{ borderColor: 'var(--mantine-color-red-7)', background: 'var(--mantine-color-red-light)' }}>
              <Text c="red" size="sm">{error}</Text>
            </Paper>
          )}
          {!connected && !error && (
            <Flex justify="center" align="center" py={60}><Loader size="lg" /><Text ml="md" c="dimmed">Connecting to backend…</Text></Flex>
          )}

          {connected && (
            <Tabs value={activeTab} onChange={setActiveTab} variant="pills" radius="md" keepMounted={false}>
              <Card mb="lg" withBorder>
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text size="sm" c="dimmed">Quick Launch</Text>
                  <Group gap="xs">
                    <Button component={Link} href="/customers" size="xs" variant="light">Customers</Button>
                    <Button component={Link} href="/pricing" size="xs" variant="light">Pricing</Button>
                    <Button component={Link} href="/webgen" size="xs" variant="light">Website Maker</Button>
                    <Button component={Link} href="/marketing" size="xs" variant="light">Marketing Console</Button>
                  </Group>
                </Group>
              </Card>

              <Tabs.List mb="lg">
                <Tabs.Tab value="overview" leftSection={<IconLayout size={16} />}>Overview</Tabs.Tab>
                <Tabs.Tab value="command" leftSection={<IconBrain size={16} />}>Command</Tabs.Tab>
                <Tabs.Tab value="agents" leftSection={<IconHexagon size={16} />} rightSection={<Badge size="xs" variant="filled" circle>{agents.length}</Badge>}>Agents</Tabs.Tab>
                <Tabs.Tab value="chat" leftSection={<IconMessage size={16} />}>Chat</Tabs.Tab>
                <Tabs.Tab value="projects" leftSection={<IconFolder size={16} />} rightSection={<Badge size="xs" variant="filled" circle>{projects.length}</Badge>}>Projects</Tabs.Tab>
                <Tabs.Tab value="tokens" leftSection={<IconChartBar size={16} />} rightSection={llmStats ? <Badge size="xs" variant="filled">{fmt.num(llmStats.tokens.total)}</Badge> : undefined}>Token Usage</Tabs.Tab>
                <Tabs.Tab value="system" leftSection={<IconSettings size={16} />}>System</Tabs.Tab>
              </Tabs.List>

              {/* ============================================================ */}
              {/* OVERVIEW TAB                                                  */}
              {/* ============================================================ */}
              <Tabs.Panel value="overview">
                <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="lg">
                  <StatCard label="Active Agents" value={agents.length} color="var(--mantine-color-agentop-5)" onClick={() => setActiveTab('agents')} />
                  <StatCard label="Projects" value={projects.length} color="var(--mantine-color-blue-5)" onClick={() => setActiveTab('projects')} />
                  <StatCard label="Tokens Used" value={llmStats ? fmt.num(llmStats.tokens.total) : '0'} color="var(--mantine-color-green-5)" onClick={() => setActiveTab('tokens')} />
                  <StatCard label="Drift Status" value={driftStatus} color={`var(--mantine-color-${driftColor(driftStatus)}-5)`} />
                </SimpleGrid>

                {/* Soul Panel */}
                <Title order={4} mb="sm">Soul Core</Title>
                <Grid mb="lg">
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <Card shadow="sm" withBorder h="100%">
                      <Group justify="space-between" mb="sm">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Active Goals</Text>
                        <Badge color="blue">{soulGoals.filter(g => !g.completed).length} open</Badge>
                      </Group>
                      {soulGoals.length === 0 ? (
                        <Text c="dimmed" size="sm" ta="center" py="md">No goals set yet.</Text>
                      ) : (
                        <Stack gap="xs" mb="sm">
                          {soulGoals.map(g => (
                            <Paper key={g.id} p="xs" withBorder style={{ opacity: g.completed ? 0.5 : 1 }}>
                              <Group justify="space-between">
                                <Text size="sm" fw={600}>{g.title}</Text>
                                <Badge size="xs" color={g.priority === 'HIGH' ? 'orange' : g.priority === 'LOW' ? 'green' : 'yellow'}>{g.priority}</Badge>
                              </Group>
                              {g.description && <Text size="xs" c="dimmed" mt={2}>{g.description}</Text>}
                            </Paper>
                          ))}
                        </Stack>
                      )}
                      <form onSubmit={submitGoal}>
                        <Stack gap="xs">
                          <TextInput size="xs" placeholder="Goal title…" value={newGoalTitle} onChange={e => setNewGoalTitle(e.currentTarget.value)} disabled={addingGoal} />
                          <TextInput size="xs" placeholder="Description (optional)" value={newGoalDesc} onChange={e => setNewGoalDesc(e.currentTarget.value)} disabled={addingGoal} />
                          <Button type="submit" size="xs" variant="filled" disabled={addingGoal || !newGoalTitle.trim()} ml="auto">{addingGoal ? 'Adding…' : 'Add Goal'}</Button>
                        </Stack>
                      </form>
                    </Card>
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <Card shadow="sm" withBorder h="100%">
                      <Group justify="space-between" mb="sm">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Self Reflection</Text>
                        <Button size="xs" variant="light" onClick={triggerReflection} loading={reflecting}>{reflecting ? 'Reflecting…' : 'Trigger Reflection'}</Button>
                      </Group>
                      {lastReflection ? (
                        <>
                          <Text size="xs" c="dimmed" ff="monospace" mb="xs">trigger: {lastReflection.trigger} · {fmt.time(lastReflection.timestamp)}</Text>
                          <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{lastReflection.reflection}</Text>
                        </>
                      ) : (
                        <Text c="dimmed" size="sm" ta="center" py="xl">No reflection generated yet. Click &quot;Trigger Reflection&quot; to prompt soul_core.</Text>
                      )}
                    </Card>
                  </Grid.Col>
                </Grid>

                {/* LLM At A Glance */}
                {llmStats && (
                  <>
                    <Title order={4} mb="sm">LLM Usage At A Glance</Title>
                    <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="lg">
                      <StatCard label="Total Requests" value={fmt.num(llmStats.stats.total_requests)} color="var(--mantine-color-agentop-5)" onClick={() => setActiveTab('tokens')} />
                      <StatCard label="Tokens (in + out)" value={fmt.num(llmStats.tokens.total)} color="var(--mantine-color-green-5)" />
                      <StatCard label="Cost (USD)" value={`$${llmStats.budget.spent_usd.toFixed(4)}`} color="var(--mantine-color-yellow-5)" />
                      <StatCard label="Avg Latency" value={`${llmStats.stats.avg_latency_ms.toFixed(0)}ms`} color="var(--mantine-color-agentop-5)" />
                    </SimpleGrid>
                  </>
                )}

                {/* Live Activity */}
                <Group mb="sm" gap="xs" align="center">
                  <Title order={4}>Live Activity</Title>
                  <Indicator color={sseConnected ? 'green' : 'red'} processing={sseConnected} size={10}><span /></Indicator>
                  <Text size="xs" c="dimmed">{sseConnected ? 'streaming' : 'disconnected'}</Text>
                </Group>
                <Card shadow="sm" withBorder mb="lg">
                  <ScrollArea h={250} type="auto">
                    {liveEvents.length === 0 ? (
                      <Text c="dimmed" ta="center" py="xl" size="sm">{sseConnected ? 'Waiting for agent activity…' : 'Connecting to live stream…'}</Text>
                    ) : (
                      <Stack gap={2}>
                        {liveEvents.slice(-20).map((ev, i) => {
                          const isError = ev.type === 'task_failed';
                          const color = isError ? 'red' : ev.type === 'llm_response' ? 'violet' : ev.type === 'task_completed' ? 'green' : 'dimmed';
                          return (
                            <Group key={i} gap="xs" wrap="nowrap" px="xs" py={2}>
                              <Text size="xs" ff="monospace" c="dimmed" style={{ flexShrink: 0, width: 60 }}>{new Date(ev.timestamp).toLocaleTimeString()}</Text>
                              <Badge size="xs" color={color} variant="light" style={{ flexShrink: 0 }}>{ev.type}</Badge>
                              {ev.data.agent_id ? <Badge size="xs" variant="outline" style={{ flexShrink: 0 }}>{String(ev.data.agent_id)}</Badge> : null}
                              <Text size="xs" c="dimmed" truncate>{String(ev.data.tool_name || ev.data.detail || ev.data.model || '')}</Text>
                            </Group>
                          );
                        })}
                        <div ref={liveEndRef} />
                      </Stack>
                    )}
                  </ScrollArea>
                </Card>
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* COMMAND TAB — Mission Control Org-Chart                      */}
              {/* ============================================================ */}
              <Tabs.Panel value="command">
                <OrchestrationHub agents={agents} />
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* AGENTS TAB                                                    */}
              {/* ============================================================ */}
              <Tabs.Panel value="agents">
                <Group justify="space-between" mb="md">
                  <Title order={4}>All Agents ({agents.length})</Title>
                  {selectedAgent && (
                    <Button size="xs" variant="subtle" leftSection={<IconChevronLeft size={14} />} onClick={() => setSelectedAgent(null)}>Back to All</Button>
                  )}
                </Group>

                {selectedAgent ? (() => {
                  const agent = agents.find(a => a.agent_id === selectedAgent);
                  const state = getAgentState(selectedAgent);
                  const mem = memoryUsage.find(m => m.agent_id === selectedAgent);
                  if (!agent) return null;
                  return (
                    <Card shadow="sm" withBorder style={{ borderColor: 'var(--mantine-color-agentop-5)' }}>
                      <Group justify="space-between" mb="md">
                        <div>
                          <Title order={3}>{agent.agent_id}</Title>
                          <Text size="sm" c="dimmed">{agent.role}</Text>
                        </div>
                        <Group gap="xs">
                          <Badge color={impactColor(agent.change_impact_level)}>{agent.change_impact_level}</Badge>
                          <Badge color={state?.status === 'ACTIVE' ? 'green' : state?.status === 'ERROR' ? 'red' : 'blue'}>{state?.status || 'IDLE'}</Badge>
                        </Group>
                      </Group>

                      <SimpleGrid cols={3} mb="md">
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{state?.total_actions || 0}</Text><Text size="xs" c="dimmed">Total Actions</Text></Paper>
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="green">{mem ? `${mem.size_mb.toFixed(2)} MB` : '0 MB'}</Text><Text size="xs" c="dimmed">Memory Usage</Text></Paper>
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c={state?.error_count ? 'red' : 'green'}>{state?.error_count || 0}</Text><Text size="xs" c="dimmed">Errors</Text></Paper>
                      </SimpleGrid>

                      <Stack gap="md">
                        <div>
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={4}>Namespace</Text>
                          <Code>{agent.memory_namespace}</Code>
                        </div>
                        <div>
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={4}>Allowed Actions</Text>
                          <Stack gap={4}>{agent.allowed_actions.map((a, i) => <Paper key={i} p="xs" withBorder><Text size="xs">{a}</Text></Paper>)}</Stack>
                        </div>
                        <div>
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={4}>Tool Permissions</Text>
                          <Group gap={4}>{agent.tool_permissions.map(t => <Badge key={t} size="sm" variant="light">{t}</Badge>)}</Group>
                        </div>
                        <div>
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={4}>System Prompt</Text>
                          <Code block style={{ maxHeight: 200, overflow: 'auto' }}>{agent.system_prompt}</Code>
                        </div>
                        <Button variant="filled" onClick={() => { setChatAgent(agent.agent_id); setActiveTab('chat'); }} leftSection={<IconMessage size={16} />}>
                          Chat with {agent.agent_id}
                        </Button>
                      </Stack>
                    </Card>
                  );
                })() : (
                  <>
                    {([0, 1, 2, 3] as number[]).map(tier => {
                      const tierAgents = agentsByTier[tier];
                      if (!tierAgents?.length) return null;
                      return (
                        <Box key={tier} mb="xl">
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb="sm" pb={6} style={{ borderBottom: '1px solid var(--mantine-color-dark-4)', letterSpacing: '0.8px' }}>
                            {TIER_LABELS[tier]}
                          </Text>
                          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                            {tierAgents.map(agent => {
                              const state = getAgentState(agent.agent_id);
                              const isSoul = agent.agent_id === 'soul_core';
                              return (
                                <Card key={agent.agent_id} shadow="sm" withBorder padding="md"
                                  style={{ cursor: 'pointer', ...(isSoul ? { borderColor: 'var(--mantine-color-agentop-5)', boxShadow: '0 0 16px rgba(108,99,255,0.15)' } : {}) }}
                                  onClick={() => setSelectedAgent(agent.agent_id)}
                                >
                                  <Group justify="space-between" mb={4}>
                                    <Text fw={700} size="lg" c={isSoul ? 'agentop' : undefined}>{agent.agent_id}</Text>
                                    <Group gap={4}>
                                      <Badge size="xs" color={impactColor(agent.change_impact_level)}>{agent.change_impact_level}</Badge>
                                      <Badge size="xs" color={state?.status === 'ACTIVE' ? 'green' : state?.status === 'ERROR' ? 'red' : 'blue'}>{state?.status || 'IDLE'}</Badge>
                                    </Group>
                                  </Group>
                                  <Text size="xs" c="dimmed" mb="sm">{agent.role}</Text>
                                  <Stack gap={4}>
                                    <Group justify="space-between"><Text size="xs" c="dimmed">Namespace</Text><Text size="xs" ff="monospace">{agent.memory_namespace}</Text></Group>
                                    <Group justify="space-between"><Text size="xs" c="dimmed">Memory</Text><Text size="xs" ff="monospace">{fmt.mb(state?.memory_size_bytes || 0)}</Text></Group>
                                    <Group justify="space-between"><Text size="xs" c="dimmed">Actions</Text><Text size="xs" ff="monospace">{state?.total_actions || 0}</Text></Group>
                                    <Group justify="space-between"><Text size="xs" c="dimmed">Errors</Text><Text size="xs" ff="monospace">{state?.error_count || 0}</Text></Group>
                                  </Stack>
                                  <Group gap={4} mt="sm">
                                    {agent.tool_permissions.slice(0, 4).map(t => <Badge key={t} size="xs" variant="light">{t}</Badge>)}
                                    {agent.tool_permissions.length > 4 && <Badge size="xs" variant="light">+{agent.tool_permissions.length - 4}</Badge>}
                                  </Group>
                                </Card>
                              );
                            })}
                          </SimpleGrid>
                        </Box>
                      );
                    })}
                  </>
                )}
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* CHAT TAB                                                      */}
              {/* ============================================================ */}
              <Tabs.Panel value="chat">
                <Grid>
                  {/* Agent sidebar */}
                  <Grid.Col span={{ base: 12, md: 3 }}>
                    <Card shadow="sm" withBorder>
                      <Group justify="space-between" mb="sm">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Agents</Text>
                        <Badge size="xs" variant="light">{agents.length}</Badge>
                      </Group>
                      <ScrollArea h={560} type="auto">
                        <Stack gap={4}>
                          {agents.map(a => {
                            const state = getAgentState(a.agent_id);
                            const selected = chatAgent === a.agent_id;
                            return (
                              <UnstyledButton key={a.agent_id} onClick={() => setChatAgent(a.agent_id)} p="xs" style={{
                                borderRadius: 'var(--mantine-radius-sm)',
                                border: `1px solid ${selected ? 'var(--mantine-color-agentop-5)' : 'var(--mantine-color-dark-4)'}`,
                                background: selected ? 'var(--mantine-color-agentop-light)' : 'transparent',
                                transition: 'all 150ms ease',
                              }}>
                                <Group justify="space-between">
                                  <Group gap={6}>
                                    <ThemeIcon size="xs" variant="light" color={selected ? 'agentop' : 'gray'}><IconRobot size={12} /></ThemeIcon>
                                    <Text size="sm" fw={600} c={selected ? 'agentop' : undefined}>{a.agent_id.replace(/_/g, ' ')}</Text>
                                  </Group>
                                  <Badge size="xs" color={state?.status === 'ACTIVE' ? 'green' : 'blue'}>{state?.status || 'IDLE'}</Badge>
                                </Group>
                                <Text size="xs" c="dimmed" truncate mt={2}>{a.role}</Text>
                              </UnstyledButton>
                            );
                          })}
                        </Stack>
                      </ScrollArea>
                    </Card>
                  </Grid.Col>

                  {/* Chat panel */}
                  <Grid.Col span={{ base: 12, md: 9 }}>
                    <Card shadow="sm" withBorder style={{ display: 'flex', flexDirection: 'column', height: 680 }}>
                      {/* Chat header */}
                      <Group justify="space-between" mb="sm" pb="sm" style={{ borderBottom: '1px solid var(--mantine-color-dark-4)' }}>
                        <Group gap="xs">
                          <ThemeIcon size="md" variant="light" color="agentop"><IconRobot size={18} /></ThemeIcon>
                          <div>
                            <Text fw={600} size="sm">{chatAgent.replace(/_/g, ' ')}</Text>
                            <Text size="xs" c="dimmed">{agents.find(a => a.agent_id === chatAgent)?.role || 'Agent'}</Text>
                          </div>
                        </Group>
                        <Group gap="sm">
                          {chatLoading && <Badge size="sm" color="yellow" variant="dot" tt="none">Processing… {chatElapsed}s</Badge>}
                          {llmStats && <Text size="xs" c="dimmed" ff="monospace">{fmt.num(llmStats.tokens.total)} tokens</Text>}
                          {chatMessages.length > 0 && (
                            <Tooltip label="Clear chat">
                              <Button variant="subtle" color="gray" size="compact-xs" onClick={() => setChatMessages([])}>
                                <IconX size={14} />
                              </Button>
                            </Tooltip>
                          )}
                        </Group>
                      </Group>

                      {/* Message area */}
                      <ScrollArea style={{ flex: 1 }} type="auto" mb="sm">
                        <Stack gap="sm" p="xs">
                          {chatMessages.length === 0 && (
                            <Stack align="center" py="xl" gap="md">
                              <ThemeIcon size={48} variant="light" color="agentop" radius="xl"><IconMessage size={24} /></ThemeIcon>
                              <div style={{ textAlign: 'center' }}>
                                <Text fw={600} mb={4}>Chat with {chatAgent.replace(/_/g, ' ')}</Text>
                                <Text size="xs" c="dimmed" maw={400}>
                                  {agents.find(a => a.agent_id === chatAgent)?.role || 'Send a message to start a conversation.'}
                                </Text>
                                <Text size="xs" c="dimmed" mt={8}>🔒 Runs locally via Ollama · No data leaves your machine</Text>
                              </div>
                              {/* Quick prompts */}
                              <SimpleGrid cols={{ base: 1, xs: 2 }} spacing="xs" mt="sm" style={{ maxWidth: 480, width: '100%' }}>
                                {[
                                  { label: '📊 System status', prompt: 'Give me a summary of the current system status' },
                                  { label: '🧠 What can you do?', prompt: 'What are your capabilities and how can you help me?' },
                                  { label: '📝 Analyze my project', prompt: 'Analyze the project structure and give me insights' },
                                  { label: '💡 Suggest improvements', prompt: 'What improvements would you suggest for this system?' },
                                ].map(q => (
                                  <Button key={q.label} variant="light" color="gray" size="xs" fullWidth justify="flex-start"
                                    style={{ border: '1px solid var(--mantine-color-dark-4)' }}
                                    onClick={() => { setChatInput(q.prompt); }}
                                  >
                                    {q.label}
                                  </Button>
                                ))}
                              </SimpleGrid>
                            </Stack>
                          )}
                          {chatMessages.map((m, i) => (
                            <Group key={i} gap="xs" align="flex-start" style={{ justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                              {m.role === 'agent' && (
                                <ThemeIcon size="sm" variant="light" color="agentop" radius="xl" mt={4}><IconRobot size={12} /></ThemeIcon>
                              )}
                              <Paper p="sm" radius="md"
                                style={{
                                  maxWidth: '80%',
                                  background: m.role === 'user' ? 'var(--mantine-color-agentop-filled)' : 'var(--mantine-color-dark-6)',
                                  border: m.role === 'agent' ? '1px solid var(--mantine-color-dark-4)' : 'none',
                                }}
                              >
                                {m.role === 'agent' && m.agent && (
                                  <Group gap={6} mb={4}>
                                    <Text size="xs" fw={600} c="agentop">{m.agent.replace(/_/g, ' ')}</Text>
                                    {m.drift && <Badge size="xs" color={driftColor(m.drift)}>{m.drift}</Badge>}
                                    {m.timestamp && <Text size="xs" c="dimmed">{fmt.time(m.timestamp)}</Text>}
                                  </Group>
                                )}
                                <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }} c={m.role === 'user' ? 'white' : undefined}>{m.content}</Text>
                                {m.role === 'user' && m.timestamp && (
                                  <Text size="xs" c="rgba(255,255,255,0.5)" ta="right" mt={4}>{fmt.time(m.timestamp)}</Text>
                                )}
                              </Paper>
                              {m.role === 'user' && (
                                <ThemeIcon size="sm" variant="filled" color="agentop" radius="xl" mt={4}><IconSend size={10} /></ThemeIcon>
                              )}
                            </Group>
                          ))}
                          {chatLoading && (
                            <Group gap="xs" align="flex-start">
                              <ThemeIcon size="sm" variant="light" color="agentop" radius="xl" mt={4}><IconRobot size={12} /></ThemeIcon>
                              <Paper p="sm" radius="md" style={{ background: 'var(--mantine-color-dark-6)', border: '1px solid var(--mantine-color-dark-4)' }}>
                                <Group gap="xs"><Loader size="xs" color="agentop" /><Text size="xs" c="dimmed">Thinking… {chatElapsed}s</Text></Group>
                              </Paper>
                            </Group>
                          )}
                          <div ref={chatEndRef} />
                        </Stack>
                      </ScrollArea>

                      {/* Input area */}
                      <form onSubmit={sendMessage}>
                        <Paper p="xs" withBorder radius="md" style={{ background: 'var(--mantine-color-dark-7)' }}>
                          <Textarea
                            placeholder={`Message ${chatAgent.replace(/_/g, ' ')}… (Enter to send, Shift+Enter for newline)`}
                            value={chatInput}
                            onChange={e => setChatInput(e.currentTarget.value)}
                            disabled={chatLoading}
                            autosize
                            minRows={1}
                            maxRows={4}
                            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(e); } }}
                            styles={{ input: { border: 'none', background: 'transparent', fontSize: 'var(--mantine-font-size-sm)' } }}
                          />
                          <Group justify="space-between" mt={4}>
                            <Text size="xs" c="dimmed">Press Enter to send · Shift+Enter for newline</Text>
                            <Button type="submit" disabled={chatLoading || !chatInput.trim()} size="compact-sm" leftSection={<IconSend size={14} />}>
                              Send
                            </Button>
                          </Group>
                        </Paper>
                      </form>
                    </Card>
                  </Grid.Col>
                </Grid>
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* PROJECTS TAB                                                  */}
              {/* ============================================================ */}
              <Tabs.Panel value="projects">
                <Group justify="space-between" mb="md">
                  <Title order={4}>Projects &amp; Outputs</Title>
                  <Group gap="xs">
                    <Button size="xs" variant={projectFilter === 'all' ? 'filled' : 'light'} onClick={() => setProjectFilter('all')}>All ({projects.length})</Button>
                    {Object.entries(projectTypes).map(([type, count]) => (
                      <Button key={type} size="xs" variant={projectFilter === type ? 'filled' : 'light'} onClick={() => setProjectFilter(type)}>
                        {projectTypeInfo(type).label} ({count})
                      </Button>
                    ))}
                  </Group>
                </Group>

                {selectedProject ? (
                  <>
                    <Button size="xs" variant="subtle" leftSection={<IconChevronLeft size={14} />} onClick={() => { setSelectedProject(null); setProjectFiles([]); }} mb="md">Back to Projects</Button>
                    <Card shadow="sm" withBorder>
                      <Group justify="space-between" mb="md">
                        <div><Title order={3}>{selectedProject.name}</Title><Text size="xs" c="dimmed" ff="monospace">{selectedProject.path}</Text></div>
                        <Badge color={projectTypeInfo(selectedProject.type).color} size="lg">{projectTypeInfo(selectedProject.type).label}</Badge>
                      </Group>
                      <SimpleGrid cols={4} mb="md">
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{selectedProject.file_count || projectFiles.length}</Text><Text size="xs" c="dimmed">Files</Text></Paper>
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{selectedProject.total_size_mb || '—'}</Text><Text size="xs" c="dimmed">MB</Text></Paper>
                        <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="green">{selectedProject.status || 'Active'}</Text><Text size="xs" c="dimmed">Status</Text></Paper>
                        <Paper p="sm" withBorder ta="center"><Text fw={600} c="dimmed">{fmt.date(selectedProject.created_at)}</Text><Text size="xs" c="dimmed">Created</Text></Paper>
                      </SimpleGrid>
                      {projectFiles.length > 0 && (
                        <>
                          <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb="xs">Files</Text>
                          <ScrollArea h={400} type="auto">
                            <Stack gap={4}>
                              {projectFiles.map(f => (
                                <Paper key={f.path} p="xs" withBorder>
                                  <Group justify="space-between" wrap="nowrap">
                                    <Group gap="xs" wrap="nowrap" style={{ overflow: 'hidden' }}>
                                      <IconFileText size={16} />
                                      <Text size="xs" ff="monospace" truncate>{f.name}</Text>
                                    </Group>
                                    <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
                                      <Badge size="xs" variant="light">{f.extension || 'file'}</Badge>
                                      <Text size="xs" c="dimmed">{fmt.size(f.size_bytes)}</Text>
                                    </Group>
                                  </Group>
                                </Paper>
                              ))}
                            </Stack>
                          </ScrollArea>
                        </>
                      )}
                    </Card>
                  </>
                ) : (
                  <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                    {filteredProjects.length === 0 ? (
                      <Card shadow="sm" withBorder style={{ gridColumn: '1 / -1' }}>
                        <Text c="dimmed" ta="center" py="xl">No projects found. Generate a website or content to see outputs here.</Text>
                      </Card>
                    ) : (
                      filteredProjects.map(project => (
                        <Card key={`${project.type}-${project.id}`} shadow="sm" withBorder style={{ cursor: 'pointer' }} onClick={() => loadProjectFiles(project)}>
                          <Group justify="space-between" mb={4}>
                            <Text fw={700}>{project.name}</Text>
                            <Badge size="sm" color={projectTypeInfo(project.type).color}>{projectTypeInfo(project.type).label}</Badge>
                          </Group>
                          <Text size="xs" c="dimmed" ff="monospace" mb="sm">{project.id}</Text>
                          <Stack gap={4}>
                            {project.file_count !== undefined && <Group justify="space-between"><Text size="xs" c="dimmed">Files</Text><Text size="xs">{project.file_count}</Text></Group>}
                            {project.total_size_mb !== undefined && <Group justify="space-between"><Text size="xs" c="dimmed">Size</Text><Text size="xs">{project.total_size_mb} MB</Text></Group>}
                            {project.status && <Group justify="space-between"><Text size="xs" c="dimmed">Status</Text><Text size="xs">{project.status}</Text></Group>}
                            <Group justify="space-between"><Text size="xs" c="dimmed">Created</Text><Text size="xs">{fmt.date(project.created_at)}</Text></Group>
                          </Stack>
                        </Card>
                      ))
                    )}
                  </SimpleGrid>
                )}
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* TOKEN USAGE TAB                                               */}
              {/* ============================================================ */}
              <Tabs.Panel value="tokens">
                <Title order={4} mb="md">Token Usage &amp; LLM Capacity</Title>

                {llmStats ? (
                  <>
                    <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="lg">
                      <StatCard label="Input Tokens" value={fmt.num(llmStats.tokens.total_in)} color="var(--mantine-color-agentop-5)" />
                      <StatCard label="Output Tokens" value={fmt.num(llmStats.tokens.total_out)} color="var(--mantine-color-green-5)" />
                      <StatCard label="Total Tokens" value={fmt.num(llmStats.tokens.total)} color="var(--mantine-color-yellow-5)" />
                      <StatCard label="Avg Latency" value={`${llmStats.stats.avg_latency_ms.toFixed(0)}ms`} color="var(--mantine-color-agentop-5)" />
                    </SimpleGrid>

                    {/* Budget */}
                    <Card shadow="sm" withBorder mb="lg">
                      <Group justify="space-between" mb="xs">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Budget</Text>
                        <Text size="sm" ff="monospace">${llmStats.budget.spent_usd.toFixed(4)} / ${llmStats.budget.monthly_limit_usd.toFixed(2)}</Text>
                      </Group>
                      <Progress
                        value={Math.min(llmStats.budget.percent_used, 100)}
                        color={llmStats.budget.percent_used > 80 ? 'red' : llmStats.budget.percent_used > 50 ? 'yellow' : 'green'}
                        size="md"
                        radius="sm"
                        mb="xs"
                      />
                      <Group justify="space-between">
                        <Text size="xs" c="dimmed">{llmStats.budget.percent_used.toFixed(1)}% used</Text>
                        <Text size="xs" c="dimmed">${llmStats.budget.remaining_usd.toFixed(2)} remaining</Text>
                      </Group>
                    </Card>

                    {/* Routing + Time Estimates */}
                    <Grid mb="lg">
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <Card shadow="sm" withBorder h="100%">
                          <Text fw={600} size="sm" tt="uppercase" c="dimmed" mb="sm">Routing Breakdown</Text>
                          <Stack gap="xs">
                            <Group justify="space-between"><Text size="sm" c="dimmed">Total Requests</Text><Text size="sm" fw={700}>{fmt.num(llmStats.stats.total_requests)}</Text></Group>
                            <Group justify="space-between"><Text size="sm" c="dimmed">Local (Free)</Text><Text size="sm" fw={700} c="green">{fmt.num(llmStats.stats.local_requests)}</Text></Group>
                            <Group justify="space-between"><Text size="sm" c="dimmed">Cloud (Paid)</Text><Text size="sm" fw={700} c="yellow">{fmt.num(llmStats.stats.cloud_requests)}</Text></Group>
                            <Group justify="space-between"><Text size="sm" c="dimmed">Cost/Request (avg)</Text><Text size="sm">${llmStats.stats.cost_per_request_avg.toFixed(6)}</Text></Group>
                          </Stack>
                        </Card>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <Card shadow="sm" withBorder h="100%">
                          <Text fw={600} size="sm" tt="uppercase" c="dimmed" mb="xs">Time Estimates</Text>
                          <Text size="xs" c="dimmed" mb="sm">Estimated completion times for a 2048-token response:</Text>
                          {llmCapacity && llmCapacity.model_capacities.filter(m => m.available).length > 0 ? (
                            <Stack gap="xs">
                              {llmCapacity.model_capacities.filter(m => m.available).map(model => {
                                const estSec = Math.round(2048 / model.estimated_tokens_per_second);
                                const timeStr = estSec >= 60 ? `${Math.floor(estSec / 60)}m ${estSec % 60}s` : `${estSec}s`;
                                return (
                                  <Paper key={model.model_id} p="xs" withBorder>
                                    <Group justify="space-between" wrap="nowrap">
                                      <Group gap="xs" wrap="nowrap"><Text size="sm" fw={600}>{model.model_id}</Text><Text size="xs" c="dimmed">{model.parameters}</Text></Group>
                                      <Group gap="sm" wrap="nowrap" style={{ flexShrink: 0 }}>
                                        <Text size="xs" c="dimmed">{model.estimated_tokens_per_second} tok/s</Text>
                                        <Text size="sm" fw={700} c="agentop" ff="monospace">~{timeStr}</Text>
                                      </Group>
                                    </Group>
                                  </Paper>
                                );
                              })}
                            </Stack>
                          ) : (
                            <Text c="dimmed" size="sm" ta="center" py="md">No models available for estimation.</Text>
                          )}
                        </Card>
                      </Grid.Col>
                    </Grid>

                    {/* Cost Log */}
                    {llmStats.cost_log.length > 0 && (
                      <Card shadow="sm" withBorder mb="lg">
                        <Group justify="space-between" mb="sm">
                          <Text fw={600} size="sm" tt="uppercase" c="dimmed">Recent Cost Log</Text>
                          <Badge size="sm">{llmStats.cost_log.length} entries</Badge>
                        </Group>
                        <ScrollArea>
                          <Table striped highlightOnHover withTableBorder withColumnBorders fz="xs" ff="monospace">
                            <Table.Thead>
                              <Table.Tr>
                                <Table.Th>Time</Table.Th><Table.Th>Dest</Table.Th><Table.Th>Model</Table.Th><Table.Th>Task</Table.Th>
                                <Table.Th>In</Table.Th><Table.Th>Out</Table.Th><Table.Th>Latency</Table.Th><Table.Th>Cost</Table.Th>
                              </Table.Tr>
                            </Table.Thead>
                            <Table.Tbody>
                              {llmStats.cost_log.map((entry, i) => (
                                <Table.Tr key={i}>
                                  <Table.Td>{fmt.time(entry.timestamp)}</Table.Td>
                                  <Table.Td><Badge size="xs" color={entry.destination === 'local' ? 'green' : 'yellow'}>{entry.destination}</Badge></Table.Td>
                                  <Table.Td>{entry.model}</Table.Td>
                                  <Table.Td>{entry.task}</Table.Td>
                                  <Table.Td>{fmt.num(entry.tokens_in)}</Table.Td>
                                  <Table.Td>{fmt.num(entry.tokens_out)}</Table.Td>
                                  <Table.Td>{entry.latency_ms.toFixed(0)}ms</Table.Td>
                                  <Table.Td>${entry.cost_usd.toFixed(6)}</Table.Td>
                                </Table.Tr>
                              ))}
                            </Table.Tbody>
                          </Table>
                        </ScrollArea>
                      </Card>
                    )}
                  </>
                ) : (
                  <Card shadow="sm" withBorder><Text c="dimmed" ta="center" py="xl">Loading LLM stats…</Text></Card>
                )}

                {/* Model Capacity */}
                {llmCapacity && (
                  <>
                    <Title order={4} mb="sm" mt="lg">Model Capacity ({llmCapacity.total_known_models} known · {llmCapacity.available_models.length + llmCapacity.model_capacities.filter(m => m.provider === 'cloud' && m.available).length} available)</Title>

                    {/* Local Models */}
                    {llmCapacity.model_capacities.filter(m => m.provider !== 'cloud').length > 0 && (
                      <>
                        <Group gap="xs" mb="sm">
                          <ThemeIcon size="sm" variant="light" color="green"><IconCpu size={14} /></ThemeIcon>
                          <Text fw={600} size="sm">Local Models (Ollama)</Text>
                          <Text size="xs" c="dimmed">— free, runs on your hardware</Text>
                        </Group>
                        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} mb="lg">
                          {llmCapacity.model_capacities.filter(m => m.provider !== 'cloud').map(model => (
                            <Card key={model.model_id} shadow="sm" withBorder style={{ opacity: model.available ? 1 : 0.5 }}>
                              <Group justify="space-between" mb="xs">
                                <Text fw={700} ff="monospace" size="sm">{model.model_id}</Text>
                                <Badge color={model.available ? 'green' : 'red'} size="sm">{model.available ? 'Available' : 'Not Pulled'}</Badge>
                              </Group>
                              <Stack gap={4}>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Family</Text><Text size="xs">{model.family}</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Parameters</Text><Text size="xs">{model.parameters}</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">VRAM</Text><Text size="xs">{model.vram_gb} GB</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Context</Text><Text size="xs">{fmt.num(model.context_window)} tokens</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Speed</Text><Text size="xs">{model.speed_tier}</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Quality</Text><Text size="xs">{model.quality_tier}</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Est. Speed</Text><Text size="xs">{model.estimated_tokens_per_second} tok/s</Text></Group>
                              </Stack>
                              {!model.available && (
                                <Code block mt="xs" style={{ fontSize: 'var(--mantine-font-size-xs)' }}>ollama pull {model.model_id}</Code>
                              )}
                              {model.best_for.length > 0 && (
                                <Group gap={4} mt="xs">{model.best_for.slice(0, 3).map(u => <Badge key={u} size="xs" variant="light">{u}</Badge>)}</Group>
                              )}
                            </Card>
                          ))}
                        </SimpleGrid>
                      </>
                    )}

                    {/* Cloud Models */}
                    {llmCapacity.model_capacities.filter(m => m.provider === 'cloud').length > 0 && (
                      <>
                        <Group gap="xs" mb="sm">
                          <ThemeIcon size="sm" variant="light" color="blue"><IconCloud size={14} /></ThemeIcon>
                          <Text fw={600} size="sm">Cloud Models (OpenRouter)</Text>
                          <Text size="xs" c="dimmed">— pay-per-use, no GPU required</Text>
                        </Group>
                        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                          {llmCapacity.model_capacities.filter(m => m.provider === 'cloud').map(model => (
                            <Card key={model.model_id} shadow="sm" withBorder style={{ opacity: model.available ? 1 : 0.6, borderColor: model.available ? 'var(--mantine-color-blue-7)' : undefined }}>
                              <Group justify="space-between" mb="xs">
                                <Group gap={6}>
                                  <IconCloud size={14} color="var(--mantine-color-blue-5)" />
                                  <Text fw={700} size="sm">{model.family}</Text>
                                </Group>
                                <Badge color={model.available ? 'blue' : 'gray'} size="sm" variant="light">{model.available ? 'Configured' : 'No API Key'}</Badge>
                              </Group>
                              <Stack gap={4}>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Model ID</Text><Text size="xs" ff="monospace">{model.model_id}</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Context</Text><Text size="xs">{fmt.num(model.context_window)} tokens</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Input Cost</Text><Text size="xs" c="green">${(model as any).cost_per_m_in?.toFixed(2) ?? '?'}/M tok</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Output Cost</Text><Text size="xs" c="yellow">${(model as any).cost_per_m_out?.toFixed(2) ?? '?'}/M tok</Text></Group>
                                <Group justify="space-between"><Text size="xs" c="dimmed">Quality</Text><Text size="xs">{model.quality_tier}</Text></Group>
                              </Stack>
                              {!model.available && (
                                <Text size="xs" c="dimmed" mt="xs" ta="center">Add OPENROUTER_API_KEY to .env to enable</Text>
                              )}
                              {model.best_for.length > 0 && (
                                <Group gap={4} mt="xs">{model.best_for.slice(0, 3).map(u => <Badge key={u} size="xs" variant="light" color="blue">{u}</Badge>)}</Group>
                              )}
                            </Card>
                          ))}
                        </SimpleGrid>
                      </>
                    )}
                  </>
                )}
              </Tabs.Panel>

              {/* ============================================================ */}
              {/* SYSTEM TAB                                                    */}
              {/* ============================================================ */}
              <Tabs.Panel value="system">
                {/* Drift Monitor */}
                <Title order={4} mb="sm">Drift Monitor</Title>
                <Card shadow="sm" withBorder mb="lg">
                  <Group justify="space-between" mb="sm">
                    <Text fw={600} size="sm" tt="uppercase" c="dimmed">Drift Status</Text>
                    <Badge size="lg" color={driftColor(driftStatus)} variant="filled">{driftStatus}</Badge>
                  </Group>
                  {drift && (
                    <>
                      <Text size="sm" c="dimmed" mb="sm">Last check: {fmt.time(drift.last_check)}</Text>
                      {drift.pending_updates.length > 0 && (
                        <Box mb="sm">
                          <Text size="sm" fw={600} c="yellow" mb={4}>Pending Updates</Text>
                          {drift.pending_updates.map((u, i) => <Text key={i} size="xs" c="dimmed">• {u}</Text>)}
                        </Box>
                      )}
                      {drift.violations.length > 0 && (
                        <Box>
                          <Text size="sm" fw={600} c="red" mb={4}>Violations</Text>
                          {drift.violations.map((v, i) => (
                            <Paper key={i} p="xs" mb="xs" withBorder style={{ borderColor: 'var(--mantine-color-red-8)' }}>
                              <Text size="sm" fw={600}>{v.invariant_id}</Text>
                              <Text size="xs" c="dimmed">{v.description}</Text>
                              <Badge size="xs" color={v.severity === 'CRITICAL' ? 'red' : 'yellow'} mt={4}>{v.severity}</Badge>
                            </Paper>
                          ))}
                        </Box>
                      )}
                      {drift.pending_updates.length === 0 && drift.violations.length === 0 && (
                        <Text c="green" ta="center" py="md" fw={500}>All systems aligned. No drift detected.</Text>
                      )}
                    </>
                  )}
                </Card>

                {/* Tool Registry */}
                <Title order={4} mb="sm">Tool Registry ({tools.length})</Title>
                <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="lg">
                  {tools.map(tool => (
                    <Card key={tool.name} shadow="sm" withBorder>
                      <Text fw={600} ff="monospace" size="sm">{tool.name}</Text>
                      <Text size="xs" c="dimmed" mt={4} mb="xs">{tool.description}</Text>
                      <Group gap={4}>
                        <Badge size="xs" color={tool.modification_type === 'READ_ONLY' ? 'green' : tool.modification_type === 'STATE_MODIFY' ? 'yellow' : 'red'}>{tool.modification_type}</Badge>
                        {tool.requires_doc_update && <Badge size="xs" color="orange">DOC REQ</Badge>}
                      </Group>
                    </Card>
                  ))}
                </SimpleGrid>

                {/* Memory Overview */}
                {memoryUsage.length > 0 && (
                  <>
                    <Title order={4} mb="sm">Memory Overview</Title>
                    <Card shadow="sm" withBorder mb="lg">
                      <ScrollArea>
                        <Table striped highlightOnHover withTableBorder fz="xs" ff="monospace">
                          <Table.Thead>
                            <Table.Tr><Table.Th>Agent</Table.Th><Table.Th>Namespace</Table.Th><Table.Th>Size (MB)</Table.Th><Table.Th>Size (bytes)</Table.Th></Table.Tr>
                          </Table.Thead>
                          <Table.Tbody>
                            {memoryUsage.map(m => (
                              <Table.Tr key={m.namespace}>
                                <Table.Td>{m.agent_id}</Table.Td>
                                <Table.Td>{m.namespace}</Table.Td>
                                <Table.Td><Text c={m.size_mb > 5 ? 'red' : m.size_mb > 1 ? 'yellow' : 'green'}>{m.size_mb.toFixed(4)}</Text></Table.Td>
                                <Table.Td>{m.size_bytes.toLocaleString()}</Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                      </ScrollArea>
                    </Card>
                  </>
                )}

                {/* Folder Analysis */}
                <Title order={4} mb="sm">Folder Analysis</Title>
                <Grid mb="lg">
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <Card shadow="sm" withBorder h="100%">
                      <Group justify="space-between" mb="sm">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Browse Project</Text>
                        <Text size="xs" c="dimmed" ff="monospace">{folderCurrent}</Text>
                      </Group>
                      <Group gap="xs" mb="sm">
                        {folderParent !== null && (
                          <Button size="xs" variant="light" leftSection={<IconChevronLeft size={14} />} onClick={() => browseTo(folderParent!)} disabled={browsingFolder}>Up</Button>
                        )}
                        <Button size="xs" variant="light" ml="auto" onClick={analyzeCurrentFolder} loading={analyzingFolder} leftSection={<IconSearch size={14} />}>
                          {analyzingFolder ? 'Analyzing…' : 'Analyze'}
                        </Button>
                      </Group>
                      <ScrollArea h={300} type="auto">
                        {folderEntries.length === 0 ? (
                          <Text c="dimmed" ta="center" py="md" size="sm">{browsingFolder ? 'Loading…' : 'Empty directory'}</Text>
                        ) : (
                          <Stack gap={2}>
                            {folderEntries.map(entry => (
                              <UnstyledButton key={entry.path} onClick={() => entry.is_dir ? browseTo(entry.path) : undefined} p="xs" style={{
                                borderRadius: 'var(--mantine-radius-sm)',
                                border: '1px solid var(--mantine-color-dark-4)',
                                cursor: entry.is_dir ? 'pointer' : 'default',
                              }}>
                                <Group justify="space-between" wrap="nowrap">
                                  <Group gap="xs" wrap="nowrap" style={{ overflow: 'hidden' }}>
                                    {entry.is_dir ? <IconFolderOpen size={16} /> : <IconFileText size={16} />}
                                    <Text size="xs" ff="monospace" c={entry.is_dir ? 'agentop' : undefined} truncate>{entry.name}</Text>
                                  </Group>
                                  {entry.size_bytes !== null && <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>{fmt.size(entry.size_bytes)}</Text>}
                                </Group>
                              </UnstyledButton>
                            ))}
                          </Stack>
                        )}
                      </ScrollArea>
                    </Card>
                  </Grid.Col>
                  <Grid.Col span={{ base: 12, md: 6 }}>
                    <Card shadow="sm" withBorder h="100%">
                      <Group justify="space-between" mb="sm">
                        <Text fw={600} size="sm" tt="uppercase" c="dimmed">Analysis Results</Text>
                        {folderAnalysis && <Badge size="sm" color="green">{folderAnalysis.file_count} files · {folderAnalysis.dir_count} dirs</Badge>}
                      </Group>
                      {!folderAnalysis && !analyzingFolder && (
                        <Text c="dimmed" ta="center" py="xl" size="sm">Select a folder and click &quot;Analyze&quot; to index its contents.</Text>
                      )}
                      {analyzingFolder && <Flex justify="center" py="xl"><Loader size="md" /></Flex>}
                      {folderAnalysis && (
                        <Stack>
                          <SimpleGrid cols={3}>
                            <Paper p="xs" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{folderAnalysis.file_count}</Text><Text size="xs" c="dimmed">Files</Text></Paper>
                            <Paper p="xs" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{folderAnalysis.dir_count}</Text><Text size="xs" c="dimmed">Dirs</Text></Paper>
                            <Paper p="xs" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{folderAnalysis.total_size_mb}</Text><Text size="xs" c="dimmed">MB</Text></Paper>
                          </SimpleGrid>
                          <div>
                            <Text size="xs" fw={600} c="dimmed" mb={4}>Extensions</Text>
                            <Group gap={4}>{Object.entries(folderAnalysis.extension_summary).map(([ext, count]) => <Badge key={ext} size="xs" variant="light">{ext}: {count}</Badge>)}</Group>
                          </div>
                          <Code block style={{ maxHeight: 150, overflow: 'auto', fontSize: 10 }}>{folderAnalysis.tree}</Code>
                          {folderAgentResponse && (
                            <div>
                              <Text size="xs" fw={600} c="dimmed" mb={4}>Agent Analysis</Text>
                              <Paper p="xs" withBorder><Text size="xs" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{folderAgentResponse}</Text></Paper>
                            </div>
                          )}
                        </Stack>
                      )}
                    </Card>
                  </Grid.Col>
                </Grid>

                {/* Task Activity */}
                <Title order={4} mb="sm">Task Activity</Title>
                <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
                  <StatCard label="Running" value={taskStats.running} color="var(--mantine-color-agentop-5)" />
                  <StatCard label="Queued" value={taskStats.queued} color="var(--mantine-color-yellow-5)" />
                  <StatCard label="Completed" value={taskStats.completed} color="var(--mantine-color-green-5)" />
                  <StatCard label="Failed" value={taskStats.failed} color="var(--mantine-color-red-5)" />
                </SimpleGrid>
                <Card shadow="sm" withBorder mb="lg">
                  <ScrollArea h={350} type="auto">
                    {tasks.length === 0 ? (
                      <Text c="dimmed" ta="center" py="xl" size="sm">No tasks recorded yet.</Text>
                    ) : (
                      <Stack gap={6}>
                        {tasks.map(task => (
                          <Paper key={task.id} p="xs" withBorder style={{
                            background: task.status === 'RUNNING' ? 'var(--mantine-color-agentop-light)' : task.status === 'FAILED' ? 'var(--mantine-color-red-light)' : undefined,
                          }}>
                            <Group gap="xs" wrap="nowrap">
                              <Box w={8} h={8} style={{
                                borderRadius: '50%', flexShrink: 0,
                                background: task.status === 'RUNNING' ? 'var(--mantine-color-agentop-5)' : task.status === 'COMPLETED' ? 'var(--mantine-color-green-5)' : task.status === 'FAILED' ? 'var(--mantine-color-red-5)' : 'var(--mantine-color-yellow-5)',
                                animation: task.status === 'RUNNING' ? 'pulse 1.5s ease-in-out infinite' : 'none',
                              }} />
                              <Badge size="xs" variant="outline" style={{ flexShrink: 0 }}>{task.agent_id}</Badge>
                              <Text size="xs" truncate style={{ flex: 1 }}>{task.detail || task.action}</Text>
                              <Text size="xs" ff="monospace" c={task.status === 'RUNNING' ? 'agentop' : task.status === 'FAILED' ? 'red' : task.status === 'COMPLETED' ? 'green' : 'dimmed'} style={{ flexShrink: 0 }}>
                                {task.status === 'RUNNING' ? '● running' : task.status === 'FAILED' ? '✗ failed' : task.duration_ms !== null ? `✓ ${task.duration_ms}ms` : task.status}
                              </Text>
                              <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>{fmt.time(task.created_at)}</Text>
                            </Group>
                          </Paper>
                        ))}
                      </Stack>
                    )}
                  </ScrollArea>
                </Card>

                {/* Recent Tool Logs */}
                <Title order={4} mb="sm">Recent Tool Logs</Title>
                <Card shadow="sm" withBorder>
                  {logs.length === 0 ? (
                    <Text c="dimmed" ta="center" py="md" size="sm">No tool executions yet</Text>
                  ) : (
                    <ScrollArea>
                      <Table striped highlightOnHover withTableBorder fz="xs" ff="monospace">
                        <Table.Thead>
                          <Table.Tr><Table.Th>Time</Table.Th><Table.Th>Agent</Table.Th><Table.Th>Tool</Table.Th><Table.Th>Type</Table.Th><Table.Th>Status</Table.Th><Table.Th>Doc Updated</Table.Th></Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {logs.map((log, i) => (
                            <Table.Tr key={i}>
                              <Table.Td>{fmt.time(log.timestamp)}</Table.Td>
                              <Table.Td>{log.agent_id}</Table.Td>
                              <Table.Td>{log.tool_name}</Table.Td>
                              <Table.Td><Badge size="xs" color={log.modification_type === 'READ_ONLY' ? 'green' : log.modification_type === 'STATE_MODIFY' ? 'yellow' : 'red'}>{log.modification_type}</Badge></Table.Td>
                              <Table.Td>
                                <Group gap={4}><Box w={6} h={6} style={{ borderRadius: '50%', background: log.success ? 'var(--mantine-color-green-5)' : 'var(--mantine-color-red-5)' }} />{log.success ? 'OK' : 'FAIL'}</Group>
                              </Table.Td>
                              <Table.Td>{log.doc_updated ? '✓' : '—'}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </ScrollArea>
                  )}
                </Card>
              </Tabs.Panel>
            </Tabs>
          )}
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
