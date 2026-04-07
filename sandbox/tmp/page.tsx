/**
 * Agentop Dashboard — Main Page (v4 — Sidebar Layout)
 *
 * UX Laws Applied:
 *   Jakob's Law   → Sidebar nav (familiar pattern)
 *   Hick's Law    → 3 views instead of 8 tabs
 *   Miller's Law  → Max 7 info chunks per view
 *   Proximity Law → Related items grouped together
 *   Von Restorff  → Hero status card with glow
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
  NavLink,
  Paper,
  Progress,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
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
import LLMHealthPanel from '@/components/panels/LLMHealthPanel';

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

type ViewId = 'dashboard' | 'agents' | 'system';

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
    <Card shadow="sm" padding="lg" withBorder style={{ cursor: onClick ? 'pointer' : undefined, position: 'relative', overflow: 'hidden' }} onClick={onClick}>
      <Box style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: color || 'var(--mantine-color-dark-4)', borderRadius: '12px 12px 0 0' }} />
      <Text size="xs" c="dimmed" tt="uppercase" fw={600} mt={4}>{label}</Text>
      <Text size={rem(28)} fw={700} ff="monospace" c={color} mt={4}>{value}</Text>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard Page
// ---------------------------------------------------------------------------
export default function DashboardPage() {
  const [activeView, setActiveView] = useState<ViewId>('dashboard');
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

  // ML state
  const [mlEvalSummary, setMlEvalSummary] = useState<{ total_cases: number; avg_score: number; pass_rate: number; by_dimension: Record<string, number>; by_model: Record<string, unknown> } | null>(null);
  const [mlEvalResults, setMlEvalResults] = useState<Array<{ case_id: string; task_type: string; model: string; score: number; pass_fail: boolean; timestamp: string }>>([]);
  const [mlAbExperiments, setMlAbExperiments] = useState<Array<{ experiment_id: string; name: string; status: string; variants: unknown[] }>>([]);
  const [mlGoldenTasks, setMlGoldenTasks] = useState<Array<{ task_id: string; task_type: string; description: string; difficulty: string }>>([]);
  const [mlTrainingFiles, setMlTrainingFiles] = useState<{ files: Array<{ name: string; size_bytes: number; line_count: number }>; total_files: number; total_lines: number } | null>(null);

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
      const h = await api.health();
      setHealth(h); setConnected(true); setError(null);

      const [a, t, d, l, mem, goals] = await Promise.all([
        api.agents().catch(() => [] as AgentDefinition[]),
        api.tools().catch(() => [] as ToolDefinition[]),
        api.drift().catch(() => null),
        api.logs(30).catch(() => [] as ToolLog[]),
        api.memoryAgents().catch(() => ({ agents: [], total_size_bytes: 0, total_size_mb: 0 })),
        api.soulGoals().catch(() => ({ goals: [], count: 0 })),
      ]);
      setAgents(a); setTools(t); if (d) setDrift(d); setLogs(l);
      setMemoryUsage(mem?.agents ?? []); setSoulGoals(goals?.goals ?? []);

      try { const td = await api.tasks(30); setTasks(td.tasks); setTaskStats(td.stats); } catch {}
      try { const st = await api.status(); setAgentStates(st.agents); } catch {}
      try { setLlmStats(await api.llmStats()); } catch {}
      try { setLlmCapacity(await api.llmCapacity()); } catch {}
      try { const p = await api.projects(); setProjects(p.projects); setProjectTypes(p.types); } catch {}

      try { setMlEvalSummary(await api.mlEvalSummary()); } catch {}
      try { setMlEvalResults(await api.mlEvalResults(20)); } catch {}
      try { setMlAbExperiments(await api.mlAbExperiments()); } catch {}
      try { setMlGoldenTasks(await api.mlGoldenTasks()); } catch {}
      try { setMlTrainingFiles(await api.mlTrainingFiles()); } catch {}

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
        ← Back
      </Button>
      <DashboardLayout />
    </div>
  );

  return (
    <AppShell
      navbar={{ width: 220, breakpoint: 'sm' }}
      padding="md"
    >
      {/* ================================================================ */}
      {/* SIDEBAR — Jakob's Law: familiar left-nav pattern                  */}
      {/* Hick's Law: 3 choices, not 8                                      */}
      {/* ================================================================ */}
      <AppShell.Navbar p="sm" style={{ background: 'rgba(20,20,23,0.95)', borderRight: '1px solid rgba(255,255,255,0.06)' }}>
        {/* Brand */}
        <Box mb="lg" pt="xs">
          <Group gap="sm" align="center">
            <Box w={6} h={24} style={{ borderRadius: 3, background: 'linear-gradient(180deg, #3d96ff, #1a82ff)' }} />
            <div>
              <Text fw={700} size="md" style={{ letterSpacing: '-0.02em' }}>Agentop</Text>
              <Text size="xs" c="dimmed" mt={-2}>Control Center</Text>
            </div>
          </Group>
        </Box>

        {/* Connection status — small, top of nav */}
        <Paper p="xs" mb="md" withBorder style={{ background: connected ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)', borderColor: connected ? 'rgba(34,197,94,0.2)' : 'rgba(239,68,68,0.2)' }}>
          <Group gap={6}>
            <Box w={6} h={6} style={{ borderRadius: '50%', background: connected ? '#22c55e' : '#ef4444', animation: connected ? 'pulse 2s ease-in-out infinite' : 'none' }} />
            <Text size="xs" c={connected ? 'green' : 'red'} fw={500}>{connected ? 'Connected' : 'Offline'}</Text>
            {health && <Text size="xs" c="dimmed" ml="auto">{Math.round(health.uptime_seconds)}s</Text>}
          </Group>
        </Paper>

        {/* Nav links */}
        <Stack gap={2}>
          <NavLink
            label="Dashboard"
            leftSection={<IconLayout size={18} />}
            active={activeView === 'dashboard'}
            onClick={() => setActiveView('dashboard')}
            style={{ fontWeight: activeView === 'dashboard' ? 600 : 400 }}
          />
          <NavLink
            label="Agents"
            leftSection={<IconHexagon size={18} />}
            active={activeView === 'agents'}
            onClick={() => { setActiveView('agents'); setSelectedAgent(null); }}
            rightSection={<Badge size="xs" variant="filled" circle>{agents.length}</Badge>}
            style={{ fontWeight: activeView === 'agents' ? 600 : 400 }}
          />
          <NavLink
            label="System"
            leftSection={<IconSettings size={18} />}
            active={activeView === 'system'}
            onClick={() => setActiveView('system')}
            style={{ fontWeight: activeView === 'system' ? 600 : 400 }}
          />
        </Stack>

        {/* Spacer */}
        <Box style={{ flex: 1 }} />

        {/* Bottom nav items */}
        <Divider mb="sm" color="dark.4" />
        <Stack gap={2}>
          <NavLink
            label="OS View"
            leftSection={<IconCpu size={18} />}
            onClick={() => setOsView(true)}
            variant="subtle"
          />
          <NavLink
            label="Orchestration"
            leftSection={<IconBrain size={18} />}
            onClick={() => { setActiveView('agents'); setSelectedAgent('soul_core'); }}
            variant="subtle"
          />
        </Stack>

        {/* Drift badge at bottom */}
        <Paper p="xs" mt="sm" withBorder style={{ background: `rgba(${driftStatus === 'GREEN' ? '34,197,94' : driftStatus === 'YELLOW' ? '245,158,11' : '239,68,68'},0.06)`, borderColor: `rgba(${driftStatus === 'GREEN' ? '34,197,94' : driftStatus === 'YELLOW' ? '245,158,11' : '239,68,68'},0.2)` }}>
          <Group gap={6}>
            <Box w={6} h={6} style={{ borderRadius: '50%', background: `var(--mantine-color-${driftColor(driftStatus)}-5)`, animation: 'pulse 2s ease-in-out infinite' }} />
            <Text size="xs" fw={500} c={driftColor(driftStatus)}>Drift: {driftStatus}</Text>
          </Group>
        </Paper>
      </AppShell.Navbar>

      {/* ================================================================ */}
      {/* MAIN CONTENT                                                      */}
      {/* ================================================================ */}
      <AppShell.Main>
        {error && (
          <Paper p="sm" mb="md" withBorder style={{ borderColor: 'var(--mantine-color-red-7)', background: 'var(--mantine-color-red-light)' }}>
            <Text c="red" size="sm">{error}</Text>
          </Paper>
        )}
        {!connected && !error && (
          <Flex direction="column" justify="center" align="center" py={80} gap="md">
            <Loader size="lg" color="agentop" />
            <Text c="dimmed" size="sm">Connecting to backend…</Text>
            <Text c="dimmed" size="xs">Waiting for http://localhost:8000</Text>
          </Flex>
        )}

        {connected && activeView === 'dashboard' && (
          /* ============================================================ */
          /* DASHBOARD VIEW                                                */
          /* Miller's Law: Hero + 4 stats + soul + activity = 7 chunks     */
          /* Von Restorff: Hero card stands out with glow                  */
          /* ============================================================ */
          <Stack gap="lg">
            {/* ── Hero Status Card (Von Restorff — the memorable thing) ── */}
            <Card
              shadow="md"
              withBorder
              padding="xl"
              style={{
                position: 'relative',
                overflow: 'hidden',
                borderColor: `rgba(${driftStatus === 'GREEN' ? '34,197,94' : driftStatus === 'YELLOW' ? '245,158,11' : '239,68,68'},0.25)`,
                boxShadow: `0 0 40px rgba(${driftStatus === 'GREEN' ? '34,197,94' : driftStatus === 'YELLOW' ? '245,158,11' : '239,68,68'},0.08)`,
              }}
            >
              {/* Top accent bar */}
              <Box style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: `var(--mantine-color-${driftColor(driftStatus)}-5)`, animation: 'heroGlow 3s ease-in-out infinite' }} />

              <Group justify="space-between" align="flex-start">
                <div>
                  <Group gap="xs" mb={4}>
                    <Badge size="lg" variant="filled" color={driftColor(driftStatus)} leftSection={
                      <Box w={8} h={8} style={{ borderRadius: '50%', background: 'currentColor', animation: 'pulse 2s ease-in-out infinite' }} />
                    }>
                      {driftStatus === 'GREEN' ? 'All Systems Nominal' : driftStatus === 'YELLOW' ? 'Drift Detected' : 'Critical Alert'}
                    </Badge>
                    {health?.llm_available && <Badge variant="dot" color="green" size="sm">LLM Online</Badge>}
                  </Group>
                  <Text size="sm" c="dimmed" mt="xs">
                    {agents.length} agents · {tools.length} tools · {projects.length} projects
                  </Text>
                </div>
                <Group gap="lg">
                  {llmStats && (
                    <div style={{ textAlign: 'right' }}>
                      <Text size={rem(24)} fw={700} ff="monospace" c="agentop">{fmt.num(llmStats.tokens.total)}</Text>
                      <Text size="xs" c="dimmed">tokens used</Text>
                    </div>
                  )}
                  {llmStats && (
                    <div style={{ textAlign: 'right' }}>
                      <Text size={rem(24)} fw={700} ff="monospace" c="green">${llmStats.budget.spent_usd.toFixed(4)}</Text>
                      <Text size="xs" c="dimmed">of ${llmStats.budget.monthly_limit_usd.toFixed(2)} budget</Text>
                    </div>
                  )}
                </Group>
              </Group>
            </Card>

            {/* ── Quick Stats (Miller's Law: exactly 4) ──────────────── */}
            <SimpleGrid cols={{ base: 2, md: 4 }}>
              <StatCard label="Active Agents" value={agents.length} color="var(--mantine-color-agentop-5)" onClick={() => setActiveView('agents')} />
              <StatCard label="Tasks Running" value={taskStats.running} color="var(--mantine-color-blue-5)" />
              <StatCard label="Avg Latency" value={llmStats ? `${llmStats.stats.avg_latency_ms.toFixed(0)}ms` : '—'} color="var(--mantine-color-yellow-5)" />
              <StatCard label="Errors" value={taskStats.failed} color={taskStats.failed > 0 ? 'var(--mantine-color-red-5)' : 'var(--mantine-color-green-5)'} />
            </SimpleGrid>

            {/* ── Soul Core + Live Activity (Proximity: grouped by role) ── */}
            <Grid>
              {/* Soul Panel */}
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Card shadow="sm" withBorder h="100%">
                  <Group justify="space-between" mb="sm">
                    <Group gap="xs">
                      <ThemeIcon size="sm" variant="light" color="agentop"><IconBrain size={14} /></ThemeIcon>
                      <Text fw={600} size="sm" tt="uppercase" c="dimmed">Soul Core</Text>
                    </Group>
                    <Button size="compact-xs" variant="light" onClick={triggerReflection} loading={reflecting}>
                      {reflecting ? 'Thinking…' : 'Reflect'}
                    </Button>
                  </Group>

                  {/* Goals — show max 3 (Miller's Law) */}
                  {soulGoals.filter(g => !g.completed).length > 0 ? (
                    <Stack gap="xs" mb="sm">
                      {soulGoals.filter(g => !g.completed).slice(0, 3).map(g => (
                        <Paper key={g.id} p="xs" withBorder>
                          <Group justify="space-between">
                            <Text size="sm" fw={600}>{g.title}</Text>
                            <Badge size="xs" color={g.priority === 'HIGH' ? 'orange' : g.priority === 'LOW' ? 'green' : 'yellow'}>{g.priority}</Badge>
                          </Group>
                          {g.description && <Text size="xs" c="dimmed" mt={2}>{g.description}</Text>}
                        </Paper>
                      ))}
                      {soulGoals.filter(g => !g.completed).length > 3 && (
                        <Text size="xs" c="dimmed" ta="center">+{soulGoals.filter(g => !g.completed).length - 3} more goals</Text>
                      )}
                    </Stack>
                  ) : (
                    <Text c="dimmed" size="sm" ta="center" py="sm">No active goals</Text>
                  )}

                  {/* Add goal — compact */}
                  <form onSubmit={submitGoal}>
                    <Group gap="xs">
                      <TextInput size="xs" placeholder="New goal…" value={newGoalTitle} onChange={e => setNewGoalTitle(e.currentTarget.value)} disabled={addingGoal} style={{ flex: 1 }} />
                      <Button type="submit" size="xs" variant="filled" disabled={addingGoal || !newGoalTitle.trim()}>Add</Button>
                    </Group>
                  </form>

                  {/* Last reflection */}
                  {lastReflection && (
                    <Paper p="xs" mt="sm" withBorder style={{ background: 'rgba(26,130,255,0.04)' }}>
                      <Text size="xs" c="dimmed" ff="monospace" mb={4}>{fmt.time(lastReflection.timestamp)}</Text>
                      <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }} lineClamp={4}>{lastReflection.reflection}</Text>
                    </Paper>
                  )}
                </Card>
              </Grid.Col>

              {/* Live Activity */}
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Card shadow="sm" withBorder h="100%">
                  <Group justify="space-between" mb="sm">
                    <Group gap="xs">
                      <Indicator color={sseConnected ? 'green' : 'red'} processing={sseConnected} size={8}><span /></Indicator>
                      <Text fw={600} size="sm" tt="uppercase" c="dimmed">Live Activity</Text>
                    </Group>
                    <Text size="xs" c="dimmed">{sseConnected ? 'streaming' : 'disconnected'}</Text>
                  </Group>
                  <ScrollArea h={280} type="auto">
                    {liveEvents.length === 0 ? (
                      <Text c="dimmed" ta="center" py="xl" size="sm">{sseConnected ? 'Waiting for agent activity…' : 'Connecting…'}</Text>
                    ) : (
                      <Stack gap={2}>
                        {liveEvents.slice(-15).map((ev, i) => {
                          const isError = ev.type === 'task_failed';
                          const color = isError ? 'red' : ev.type === 'llm_response' ? 'blue' : ev.type === 'task_completed' ? 'green' : 'dimmed';
                          return (
                            <Group key={i} gap="xs" wrap="nowrap" px="xs" py={2}>
                              <Text size="xs" ff="monospace" c="dimmed" style={{ flexShrink: 0, width: 55 }}>{new Date(ev.timestamp).toLocaleTimeString()}</Text>
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
              </Grid.Col>
            </Grid>
          </Stack>
        )}

        {connected && activeView === 'agents' && (
          /* ============================================================ */
          /* AGENTS VIEW                                                   */
          /* Jakob's Law: click agent → detail + chat in same panel         */
          /* Proximity: agent info grouped with its chat                    */
          /* ============================================================ */
          <>
            {selectedAgent ? (() => {
              const agent = agents.find(a => a.agent_id === selectedAgent);
              const state = getAgentState(selectedAgent);
              const mem = memoryUsage.find(m => m.agent_id === selectedAgent);
              if (!agent) return null;

              // When viewing an agent, set it as chat target
              if (chatAgent !== selectedAgent) setChatAgent(selectedAgent);

              return (
                <Stack gap="md">
                  <Button size="xs" variant="subtle" leftSection={<IconChevronLeft size={14} />} onClick={() => setSelectedAgent(null)} w="fit-content">
                    All Agents
                  </Button>

                  {/* Agent header */}
                  <Card shadow="sm" withBorder style={{ borderColor: 'var(--mantine-color-agentop-5)' }}>
                    <Group justify="space-between" mb="md">
                      <div>
                        <Title order={3}>{agent.agent_id.replace(/_/g, ' ')}</Title>
                        <Text size="sm" c="dimmed">{agent.role}</Text>
                      </div>
                      <Group gap="xs">
                        <Badge color={impactColor(agent.change_impact_level)}>{agent.change_impact_level}</Badge>
                        <Badge color={state?.status === 'ACTIVE' ? 'green' : state?.status === 'ERROR' ? 'red' : 'blue'}>{state?.status || 'IDLE'}</Badge>
                      </Group>
                    </Group>

                    {/* Quick stats — 3 items (proximity) */}
                    <SimpleGrid cols={3} mb="md">
                      <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="agentop">{state?.total_actions || 0}</Text><Text size="xs" c="dimmed">Actions</Text></Paper>
                      <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c="green">{mem ? `${mem.size_mb.toFixed(2)} MB` : '0 MB'}</Text><Text size="xs" c="dimmed">Memory</Text></Paper>
                      <Paper p="sm" withBorder ta="center"><Text size="xl" fw={700} c={state?.error_count ? 'red' : 'green'}>{state?.error_count || 0}</Text><Text size="xs" c="dimmed">Errors</Text></Paper>
                    </SimpleGrid>

                    {/* Tools + permissions (collapsed) */}
                    <Group gap={4} mb="sm">
                      {agent.tool_permissions.map(t => <Badge key={t} size="sm" variant="light">{t}</Badge>)}
                    </Group>
                  </Card>

                  {/* Embedded Chat (Proximity: chat lives with the agent) */}
                  <Card shadow="sm" withBorder style={{ display: 'flex', flexDirection: 'column', height: 480 }}>
                    <Group justify="space-between" mb="sm" pb="sm" style={{ borderBottom: '1px solid var(--mantine-color-dark-4)' }}>
                      <Group gap="xs">
                        <ThemeIcon size="md" variant="light" color="agentop"><IconRobot size={18} /></ThemeIcon>
                        <Text fw={600} size="sm">Chat with {agent.agent_id.replace(/_/g, ' ')}</Text>
                      </Group>
                      <Group gap="sm">
                        {chatLoading && <Badge size="sm" color="yellow" variant="dot" tt="none">Processing… {chatElapsed}s</Badge>}
                        {chatMessages.length > 0 && (
                          <Tooltip label="Clear chat">
                            <Button variant="subtle" color="gray" size="compact-xs" onClick={() => setChatMessages([])}>
                              <IconX size={14} />
                            </Button>
                          </Tooltip>
                        )}
                      </Group>
                    </Group>

                    <ScrollArea style={{ flex: 1 }} type="auto" mb="sm">
                      <Stack gap="sm" p="xs">
                        {chatMessages.length === 0 && (
                          <Stack align="center" py="lg" gap="sm">
                            <ThemeIcon size={40} variant="light" color="agentop" radius="xl"><IconMessage size={20} /></ThemeIcon>
                            <Text size="sm" c="dimmed">Send a message to start chatting</Text>
                            <Text size="xs" c="dimmed">Runs locally via Ollama</Text>
                          </Stack>
                        )}
                        {chatMessages.map((m, i) => (
                          <Group key={i} gap="xs" align="flex-start" style={{ justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start' }}>
                            {m.role === 'agent' && <ThemeIcon size="sm" variant="light" color="agentop" radius="xl" mt={4}><IconRobot size={12} /></ThemeIcon>}
                            <Paper p="sm" radius="md" style={{
                              maxWidth: '80%',
                              background: m.role === 'user' ? 'var(--mantine-color-agentop-filled)' : 'var(--mantine-color-dark-6)',
                              border: m.role === 'agent' ? '1px solid var(--mantine-color-dark-4)' : 'none',
                            }}>
                              {m.role === 'agent' && m.agent && (
                                <Group gap={6} mb={4}>
                                  <Text size="xs" fw={600} c="agentop">{m.agent.replace(/_/g, ' ')}</Text>
                                  {m.drift && <Badge size="xs" color={driftColor(m.drift)}>{m.drift}</Badge>}
                                </Group>
                              )}
                              <Text size="sm" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }} c={m.role === 'user' ? 'white' : undefined}>{m.content}</Text>
                            </Paper>
                            {m.role === 'user' && <ThemeIcon size="sm" variant="filled" color="agentop" radius="xl" mt={4}><IconSend size={10} /></ThemeIcon>}
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

                    <form onSubmit={sendMessage}>
                      <Paper p="xs" withBorder radius="md" style={{ background: 'var(--mantine-color-dark-7)' }}>
                        <Textarea
                          placeholder={`Message ${agent.agent_id.replace(/_/g, ' ')}…`}
                          value={chatInput}
                          onChange={e => setChatInput(e.currentTarget.value)}
                          disabled={chatLoading}
                          autosize minRows={1} maxRows={3}
                          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(e); } }}
                          styles={{ input: { border: 'none', background: 'transparent', fontSize: 'var(--mantine-font-size-sm)' } }}
                        />
                        <Group justify="flex-end" mt={4}>
                          <Button type="submit" disabled={chatLoading || !chatInput.trim()} size="compact-sm" leftSection={<IconSend size={14} />}>Send</Button>
                        </Group>
                      </Paper>
                    </form>
                  </Card>
                </Stack>
              );
            })() : (
              /* ── Agent Grid ─────────────────────────────────────────── */
              <Stack gap="lg">
                <Group justify="space-between">
                  <Title order={3}>Agents</Title>
                  <Text size="sm" c="dimmed">{agents.length} registered</Text>
                </Group>

                {([0, 1, 2, 3] as number[]).map(tier => {
                  const tierAgents = agentsByTier[tier];
                  if (!tierAgents?.length) return null;
                  return (
                    <Box key={tier}>
                      <Text className="system-section-header" mb="sm">{TIER_LABELS[tier]}</Text>
                      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                        {tierAgents.map(agent => {
                          const state = getAgentState(agent.agent_id);
                          const isSoul = agent.agent_id === 'soul_core';
                          return (
                            <Card key={agent.agent_id} shadow="sm" withBorder padding="md"
                              style={{ cursor: 'pointer', ...(isSoul ? { borderColor: 'var(--mantine-color-agentop-5)', boxShadow: '0 0 16px rgba(26,130,255,0.15)' } : {}) }}
                              onClick={() => { setSelectedAgent(agent.agent_id); setChatAgent(agent.agent_id); setChatMessages([]); }}
                            >
                              <Group justify="space-between" mb={4}>
                                <Text fw={700} size="md" c={isSoul ? 'agentop' : undefined}>{agent.agent_id.replace(/_/g, ' ')}</Text>
                                <Group gap={4}>
                                  <Badge size="xs" color={impactColor(agent.change_impact_level)}>{agent.change_impact_level}</Badge>
                                  <Badge size="xs" color={state?.status === 'ACTIVE' ? 'green' : state?.status === 'ERROR' ? 'red' : 'blue'}>{state?.status || 'IDLE'}</Badge>
                                </Group>
                              </Group>
                              <Text size="xs" c="dimmed" lineClamp={2} mb="sm">{agent.role}</Text>
                              <Group gap={4}>
                                {agent.tool_permissions.slice(0, 3).map(t => <Badge key={t} size="xs" variant="light">{t}</Badge>)}
                                {agent.tool_permissions.length > 3 && <Badge size="xs" variant="light">+{agent.tool_permissions.length - 3}</Badge>}
                              </Group>
                            </Card>
                          );
                        })}
                      </SimpleGrid>
                    </Box>
                  );
                })}
              </Stack>
            )}
          </>
        )}

        {connected && activeView === 'system' && (
          /* ============================================================ */
          /* SYSTEM VIEW                                                   */
          /* Proximity: operational data grouped by domain                  */
          /* ============================================================ */
          <Stack gap="lg">
            <Title order={3}>System</Title>

            {/* ── LLM Health ──────────────────────────────────────────── */}
            <LLMHealthPanel />

            {/* ── Token Usage ─────────────────────────────────────────── */}
            {llmStats && (
              <>
                <Text className="system-section-header">Token Usage &amp; Budget</Text>
                <SimpleGrid cols={{ base: 2, md: 4 }} mb="sm">
                  <StatCard label="Input Tokens" value={fmt.num(llmStats.tokens.total_in)} color="var(--mantine-color-agentop-5)" />
                  <StatCard label="Output Tokens" value={fmt.num(llmStats.tokens.total_out)} color="var(--mantine-color-green-5)" />
                  <StatCard label="Total Cost" value={`$${llmStats.budget.spent_usd.toFixed(4)}`} color="var(--mantine-color-yellow-5)" />
                  <StatCard label="Avg Latency" value={`${llmStats.stats.avg_latency_ms.toFixed(0)}ms`} color="var(--mantine-color-agentop-5)" />
                </SimpleGrid>
                <Card shadow="sm" withBorder>
                  <Group justify="space-between" mb="xs">
                    <Text size="sm" fw={500}>Budget</Text>
                    <Text size="sm" ff="monospace">${llmStats.budget.spent_usd.toFixed(4)} / ${llmStats.budget.monthly_limit_usd.toFixed(2)}</Text>
                  </Group>
                  <Progress
                    value={Math.min(llmStats.budget.percent_used, 100)}
                    color={llmStats.budget.percent_used > 80 ? 'red' : llmStats.budget.percent_used > 50 ? 'yellow' : 'green'}
                    size="md" radius="sm"
                  />
                </Card>
              </>
            )}

            {/* ── Drift Monitor ───────────────────────────────────────── */}
            <Text className="system-section-header">Drift Monitor</Text>
            <Card shadow="sm" withBorder>
              <Group justify="space-between" mb="sm">
                <Text fw={600} size="sm">Drift Status</Text>
                <Badge size="lg" color={driftColor(driftStatus)} variant="filled">{driftStatus}</Badge>
              </Group>
              {drift && (
                <>
                  {drift.violations.length > 0 ? (
                    <Stack gap="xs">
                      {drift.violations.map((v, i) => (
                        <Paper key={i} p="xs" withBorder style={{ borderColor: 'var(--mantine-color-red-8)' }}>
                          <Group justify="space-between">
                            <Text size="sm" fw={600}>{v.invariant_id}</Text>
                            <Badge size="xs" color={v.severity === 'CRITICAL' ? 'red' : 'yellow'}>{v.severity}</Badge>
                          </Group>
                          <Text size="xs" c="dimmed">{v.description}</Text>
                        </Paper>
                      ))}
                    </Stack>
                  ) : (
                    <Text c="green" ta="center" py="sm" fw={500} size="sm">All systems aligned. No drift detected.</Text>
                  )}
                </>
              )}
            </Card>

            {/* ── Tool Registry ────────────────────────────────────────── */}
            <Text className="system-section-header">Tools ({tools.length})</Text>
            <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
              {tools.map(tool => (
                <Card key={tool.name} shadow="sm" withBorder>
                  <Text fw={600} ff="monospace" size="sm">{tool.name}</Text>
                  <Text size="xs" c="dimmed" mt={4} mb="xs" lineClamp={2}>{tool.description}</Text>
                  <Group gap={4}>
                    <Badge size="xs" color={tool.modification_type === 'READ_ONLY' ? 'green' : tool.modification_type === 'STATE_MODIFY' ? 'yellow' : 'red'}>{tool.modification_type}</Badge>
                    {tool.requires_doc_update && <Badge size="xs" color="orange">DOC REQ</Badge>}
                  </Group>
                </Card>
              ))}
            </SimpleGrid>

            {/* ── ML Lab Summary ───────────────────────────────────────── */}
            <Text className="system-section-header">ML Lab</Text>
            <SimpleGrid cols={{ base: 2, md: 4 }}>
              <StatCard label="Eval Cases" value={mlEvalSummary?.total_cases ?? 0} color="var(--mantine-color-agentop-5)" />
              <StatCard label="Avg Score" value={mlEvalSummary ? `${(mlEvalSummary.avg_score * 100).toFixed(1)}%` : '—'} color="var(--mantine-color-blue-5)" />
              <StatCard label="Pass Rate" value={mlEvalSummary ? `${(mlEvalSummary.pass_rate * 100).toFixed(1)}%` : '—'} color="var(--mantine-color-green-5)" />
              <StatCard label="Training Files" value={mlTrainingFiles?.total_files ?? 0} color="var(--mantine-color-yellow-5)" />
            </SimpleGrid>

            {mlEvalSummary && Object.keys(mlEvalSummary.by_dimension).length > 0 && (
              <Card shadow="sm" withBorder>
                <Text fw={600} size="sm" mb="sm">Eval Dimensions</Text>
                <Stack gap="sm">
                  {Object.entries(mlEvalSummary.by_dimension).map(([dim, score]) => (
                    <div key={dim}>
                      <Group justify="space-between" mb={4}>
                        <Text size="xs" tt="capitalize">{dim.replace(/_/g, ' ')}</Text>
                        <Text size="xs" ff="monospace" fw={600}>{(Number(score) * 100).toFixed(1)}%</Text>
                      </Group>
                      <Progress value={Number(score) * 100} size="sm" color={Number(score) >= 0.8 ? 'green' : Number(score) >= 0.5 ? 'yellow' : 'red'} />
                    </div>
                  ))}
                </Stack>
              </Card>
            )}

            {/* ── Projects ────────────────────────────────────────────── */}
            {projects.length > 0 && (
              <>
                <Text className="system-section-header">Projects ({projects.length})</Text>
                {selectedProject ? (
                  <>
                    <Button size="xs" variant="subtle" leftSection={<IconChevronLeft size={14} />} onClick={() => { setSelectedProject(null); setProjectFiles([]); }} w="fit-content">Back</Button>
                    <Card shadow="sm" withBorder>
                      <Group justify="space-between" mb="md">
                        <div><Title order={4}>{selectedProject.name}</Title><Text size="xs" c="dimmed" ff="monospace">{selectedProject.path}</Text></div>
                        <Badge color={projectTypeInfo(selectedProject.type).color}>{projectTypeInfo(selectedProject.type).label}</Badge>
                      </Group>
                      {projectFiles.length > 0 && (
                        <ScrollArea h={300}>
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
                      )}
                    </Card>
                  </>
                ) : (
                  <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                    {filteredProjects.map(project => (
                      <Card key={`${project.type}-${project.id}`} shadow="sm" withBorder style={{ cursor: 'pointer' }} onClick={() => loadProjectFiles(project)}>
                        <Group justify="space-between" mb={4}>
                          <Text fw={700} size="sm">{project.name}</Text>
                          <Badge size="sm" color={projectTypeInfo(project.type).color}>{projectTypeInfo(project.type).label}</Badge>
                        </Group>
                        <Text size="xs" c="dimmed" ff="monospace" mb="xs">{project.id}</Text>
                        <Group justify="space-between"><Text size="xs" c="dimmed">Created</Text><Text size="xs">{fmt.date(project.created_at)}</Text></Group>
                      </Card>
                    ))}
                  </SimpleGrid>
                )}
              </>
            )}

            {/* ── Memory Overview ─────────────────────────────────────── */}
            {memoryUsage.length > 0 && (
              <>
                <Text className="system-section-header">Memory</Text>
                <Card shadow="sm" withBorder>
                  <ScrollArea>
                    <Table striped highlightOnHover withTableBorder fz="xs" ff="monospace">
                      <Table.Thead>
                        <Table.Tr><Table.Th>Agent</Table.Th><Table.Th>Namespace</Table.Th><Table.Th ta="right">Size</Table.Th></Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {memoryUsage.map(m => (
                          <Table.Tr key={m.namespace}>
                            <Table.Td>{m.agent_id}</Table.Td>
                            <Table.Td>{m.namespace}</Table.Td>
                            <Table.Td ta="right"><Text c={m.size_mb > 5 ? 'red' : m.size_mb > 1 ? 'yellow' : 'green'}>{m.size_mb.toFixed(4)} MB</Text></Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                </Card>
              </>
            )}

            {/* ── Task Activity ────────────────────────────────────────── */}
            <Text className="system-section-header">Tasks</Text>
            <SimpleGrid cols={{ base: 2, md: 4 }} mb="sm">
              <StatCard label="Running" value={taskStats.running} color="var(--mantine-color-agentop-5)" />
              <StatCard label="Queued" value={taskStats.queued} color="var(--mantine-color-yellow-5)" />
              <StatCard label="Completed" value={taskStats.completed} color="var(--mantine-color-green-5)" />
              <StatCard label="Failed" value={taskStats.failed} color="var(--mantine-color-red-5)" />
            </SimpleGrid>
            <Card shadow="sm" withBorder>
              <ScrollArea h={300} type="auto">
                {tasks.length === 0 ? (
                  <Text c="dimmed" ta="center" py="xl" size="sm">No tasks recorded yet.</Text>
                ) : (
                  <Stack gap={4}>
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
                        </Group>
                      </Paper>
                    ))}
                  </Stack>
                )}
              </ScrollArea>
            </Card>

            {/* ── Recent Tool Logs ─────────────────────────────────────── */}
            <Text className="system-section-header">Recent Tool Logs</Text>
            <Card shadow="sm" withBorder>
              {logs.length === 0 ? (
                <Text c="dimmed" ta="center" py="md" size="sm">No tool executions yet</Text>
              ) : (
                <ScrollArea>
                  <Table striped highlightOnHover withTableBorder fz="xs" ff="monospace">
                    <Table.Thead>
                      <Table.Tr><Table.Th>Time</Table.Th><Table.Th>Agent</Table.Th><Table.Th>Tool</Table.Th><Table.Th>Type</Table.Th><Table.Th>Status</Table.Th></Table.Tr>
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
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              )}
            </Card>

            {/* ── Folder Analysis ──────────────────────────────────────── */}
            <Text className="system-section-header">Folder Browser</Text>
            <Grid>
              <Grid.Col span={{ base: 12, md: 6 }}>
                <Card shadow="sm" withBorder h="100%">
                  <Group justify="space-between" mb="sm">
                    <Text fw={600} size="sm">Browse</Text>
                    <Text size="xs" c="dimmed" ff="monospace">{folderCurrent}</Text>
                  </Group>
                  <Group gap="xs" mb="sm">
                    {folderParent !== null && (
                      <Button size="xs" variant="light" leftSection={<IconChevronLeft size={14} />} onClick={() => browseTo(folderParent!)} disabled={browsingFolder}>Up</Button>
                    )}
                    <Button size="xs" variant="light" ml="auto" onClick={analyzeCurrentFolder} loading={analyzingFolder} leftSection={<IconSearch size={14} />}>
                      Analyze
                    </Button>
                  </Group>
                  <ScrollArea h={250} type="auto">
                    {folderEntries.length === 0 ? (
                      <Text c="dimmed" ta="center" py="md" size="sm">{browsingFolder ? 'Loading…' : 'Empty'}</Text>
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
                    <Text fw={600} size="sm">Analysis</Text>
                    {folderAnalysis && <Badge size="sm" color="green">{folderAnalysis.file_count} files</Badge>}
                  </Group>
                  {!folderAnalysis && !analyzingFolder && (
                    <Text c="dimmed" ta="center" py="xl" size="sm">Select a folder and click Analyze.</Text>
                  )}
                  {analyzingFolder && <Flex justify="center" py="xl"><Loader size="md" /></Flex>}
                  {folderAnalysis && (
                    <Stack>
                      <SimpleGrid cols={3}>
                        <Paper p="xs" withBorder ta="center"><Text size="lg" fw={700} c="agentop">{folderAnalysis.file_count}</Text><Text size="xs" c="dimmed">Files</Text></Paper>
                        <Paper p="xs" withBorder ta="center"><Text size="lg" fw={700} c="agentop">{folderAnalysis.dir_count}</Text><Text size="xs" c="dimmed">Dirs</Text></Paper>
                        <Paper p="xs" withBorder ta="center"><Text size="lg" fw={700} c="agentop">{folderAnalysis.total_size_mb}</Text><Text size="xs" c="dimmed">MB</Text></Paper>
                      </SimpleGrid>
                      <Group gap={4}>{Object.entries(folderAnalysis.extension_summary).map(([ext, count]) => <Badge key={ext} size="xs" variant="light">{ext}: {count}</Badge>)}</Group>
                      <Code block style={{ maxHeight: 120, overflow: 'auto', fontSize: 10 }}>{folderAnalysis.tree}</Code>
                      {folderAgentResponse && (
                        <Paper p="xs" withBorder><Text size="xs" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{folderAgentResponse}</Text></Paper>
                      )}
                    </Stack>
                  )}
                </Card>
              </Grid.Col>
            </Grid>
          </Stack>
        )}
      </AppShell.Main>
    </AppShell>
  );
}
