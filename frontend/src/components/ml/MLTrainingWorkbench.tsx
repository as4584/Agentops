'use client';

import { startTransition, useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Code,
  Divider,
  Grid,
  Group,
  Loader,
  NumberInput,
  Paper,
  Progress,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import {
  IconBolt,
  IconBrain,
  IconCheck,
  IconCopy,
  IconCpu,
  IconPlayerPlay,
  IconRefresh,
  IconSquareRoundedX,
  IconTerminal2,
} from '@tabler/icons-react';

import DatasetPicker from '@/components/ml/DatasetPicker';
import {
  type ChampionStatus,
  type StartTrainingJobPayload,
  type TrainingArtifactEntry,
  type TrainingDatasetEntry,
  type TrainingJob,
  type TrainingJobLogResponse,
  type TrainingMetricPoint,
  type TrainingWorkbenchSnapshot,
  mlTrainingApi,
} from '@/lib/mlTrainingApi';

const POLL_MS = 5000;
const LOG_POLL_MS = 2500;

const fmt = {
  num: (value: number) => value.toLocaleString(),
  pct: (value: number) => `${(value * 100).toFixed(1)}%`,
  time: (value: string | null | undefined) => {
    if (!value) return '—';
    try {
      return new Date(value).toLocaleString();
    } catch {
      return value;
    }
  },
};

function statusColor(status: TrainingJob['status']): string {
  switch (status) {
    case 'running':
      return 'green';
    case 'completed':
      return 'blue';
    case 'failed':
      return 'red';
    case 'cancelling':
      return 'yellow';
    case 'cancelled':
      return 'gray';
    default:
      return 'gray';
  }
}

function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: 'Queued',
    launching: 'Launching',
    native_curation: 'Native Curation',
    data_prep: 'Data Prep',
    completed_prep: 'Prep Complete',
    sft: 'SFT',
    dpo: 'DPO',
    gguf_export: 'GGUF Export',
    ollama_import: 'Ollama Import',
  };
  return labels[stage] ?? stage.replace(/_/g, ' ');
}

function topRecommendedTraining(items: TrainingDatasetEntry[]): string[] {
  const preferred = ['filtered_combined.jsonl', 'combined.jsonl'];
  const available = new Set(items.map(item => item.name));
  const picks = preferred.filter(name => available.has(name));
  const generated = [...items]
    .filter(item => item.name.startsWith('generated_hard_'))
    .sort((a, b) => b.modified_at.localeCompare(a.modified_at))
    .slice(0, 2)
    .map(item => item.name);
  return Array.from(new Set([...picks, ...generated]));
}

function topRecommendedDpo(items: TrainingDatasetEntry[]): string[] {
  return [...items]
    .filter(item => item.name.startsWith('live_dpo_'))
    .sort((a, b) => b.modified_at.localeCompare(a.modified_at))
    .slice(0, 8)
    .map(item => item.name);
}

function toSelectData(artifacts: TrainingArtifactEntry[]) {
  return artifacts.map(artifact => ({
    value: artifact.path,
    label: artifact.label,
  }));
}

function formatMetricValue(value: number, kind: 'loss' | 'accuracy'): string {
  return kind === 'accuracy' ? `${(value * 100).toFixed(1)}%` : value.toFixed(4);
}

function buildMetricPath(
  points: TrainingMetricPoint[],
  kind: 'loss' | 'accuracy',
  width: number,
  height: number,
  padding: number,
): string {
  if (points.length === 0) return '';

  const values = points.map((point) => (kind === 'accuracy' ? point.accuracy : point.loss));
  const minValue = kind === 'accuracy' ? 0 : Math.min(...values);
  const maxValue = kind === 'accuracy' ? 1 : Math.max(...values);
  const range = Math.max(maxValue - minValue, kind === 'accuracy' ? 1 : 0.0001);
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  return points
    .map((point, index) => {
      const x = padding + (chartWidth * index) / Math.max(points.length - 1, 1);
      const rawValue = kind === 'accuracy' ? point.accuracy : point.loss;
      const y = padding + chartHeight - ((rawValue - minValue) / range) * chartHeight;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
}

function CopyLogButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable — fall back to execCommand
      const el = document.createElement('textarea');
      el.value = text;
      el.style.position = 'fixed';
      el.style.opacity = '0';
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [text]);

  return (
    <Tooltip label={copied ? 'Copied!' : 'Copy log to clipboard'} withArrow>
      <ActionIcon
        variant="subtle"
        color={copied ? 'green' : 'gray'}
        size="sm"
        aria-label="Copy log output"
        disabled={!text}
        onClick={() => { void handleCopy(); }}
      >
        {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      </ActionIcon>
    </Tooltip>
  );
}

function ChampionBadge({ refreshKey }: { refreshKey: number }) {
  const [champion, setChampion] = useState<ChampionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const nextChampion = await mlTrainingApi.getChampion();
        if (!cancelled) {
          setChampion(nextChampion);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Champion unavailable');
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  return (
    <Paper withBorder p="md" radius="md" style={{ minWidth: 220, background: 'rgba(0,0,0,0.18)' }}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
        Champion router
      </Text>
      <Text fw={700} mt={6}>
        {champion?.model ?? 'Unavailable'}
      </Text>
      <Text size="xs" c="dimmed">
        {champion?.score == null ? 'No promotion score yet' : `Score ${(champion.score * 100).toFixed(1)}%`}
      </Text>
      <Text size="xs" c="dimmed">
        {error ?? `Promoted ${fmt.time(champion?.promoted_at)}`}
      </Text>
    </Paper>
  );
}

function MetricsChart({ activeJob }: { activeJob: TrainingJob | null }) {
  const [points, setPoints] = useState<TrainingMetricPoint[]>([]);
  const [streamState, setStreamState] = useState<'idle' | 'streaming' | 'done'>('idle');

  useEffect(() => {
    setPoints([]);
    if (!activeJob?.job_id) {
      setStreamState('idle');
      return;
    }

    setStreamState('streaming');
    const unsubscribe = mlTrainingApi.subscribeMetrics(
      activeJob.job_id,
      (point) => {
        setPoints((prev) => {
          const deduped = prev.some((entry) => entry.step === point.step && entry.ts === point.ts);
          if (deduped) return prev;
          return [...prev, point].slice(-240);
        });
      },
      () => setStreamState('done'),
    );

    return unsubscribe;
  }, [activeJob?.job_id]);

  const chartWidth = 640;
  const chartHeight = 260;
  const chartPadding = 20;
  const lossPath = useMemo(
    () => buildMetricPath(points, 'loss', chartWidth, chartHeight, chartPadding),
    [points],
  );
  const accuracyPath = useMemo(
    () => buildMetricPath(points, 'accuracy', chartWidth, chartHeight, chartPadding),
    [points],
  );
  const latestPoint = points[points.length - 1] ?? null;
  const firstStep = points[0]?.step ?? 0;
  const lastStep = latestPoint?.step ?? 0;

  return (
    <Card withBorder radius="lg" p="lg" h="100%">
      <Group justify="space-between" mb="sm">
        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Step telemetry
          </Text>
          <Title order={4}>Loss and accuracy</Title>
        </div>
        <Badge variant="light" color={streamState === 'streaming' ? 'blue' : streamState === 'done' ? 'green' : 'gray'}>
          {streamState}
        </Badge>
      </Group>

      {points.length === 0 ? (
        <Paper withBorder p="xl" radius="md" h={260} style={{ display: 'grid', placeItems: 'center' }}>
          <Text size="sm" c="dimmed" ta="center">
            {activeJob ? 'No training metrics emitted for this job yet.' : 'Start or select a job to watch live step metrics.'}
          </Text>
        </Paper>
      ) : (
        <Stack gap="xs">
          <Group gap="md">
            <Badge color="red" variant="light">
              Loss {latestPoint ? formatMetricValue(latestPoint.loss, 'loss') : '—'}
            </Badge>
            <Badge color="blue" variant="light">
              Accuracy {latestPoint ? formatMetricValue(latestPoint.accuracy, 'accuracy') : '—'}
            </Badge>
            <Text size="xs" c="dimmed">
              Steps {firstStep} → {lastStep}
            </Text>
          </Group>

          <Box h={260}>
            <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} width="100%" height="100%" role="img" aria-label="Training loss and accuracy">
              {[0.2, 0.4, 0.6, 0.8].map((ratio) => {
                const y = chartPadding + (chartHeight - chartPadding * 2) * ratio;
                return (
                  <line
                    key={ratio}
                    x1={chartPadding}
                    x2={chartWidth - chartPadding}
                    y1={y}
                    y2={y}
                    stroke="rgba(255,255,255,0.08)"
                    strokeDasharray="4 6"
                  />
                );
              })}
              <path d={lossPath} fill="none" stroke="#ff6b6b" strokeWidth="3" strokeLinecap="round" />
              <path d={accuracyPath} fill="none" stroke="#4dabf7" strokeWidth="3" strokeLinecap="round" />
            </svg>
          </Box>

          <Group justify="space-between">
            <Text size="xs" c="dimmed">
              Start step {firstStep}
            </Text>
            <Text size="xs" c="dimmed">
              Latest step {lastStep}
            </Text>
          </Group>
        </Stack>
      )}
    </Card>
  );
}

function PromoteButton({
  job,
  onPromoted,
  onError,
}: {
  job: TrainingJob;
  onPromoted: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [loading, setLoading] = useState(false);

  if (job.status !== 'completed' || job.eval_score == null) {
    return null;
  }

  const handlePromote = async () => {
    setLoading(true);
    try {
      await mlTrainingApi.promoteJob(job.job_id);
      await onPromoted();
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to promote model');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button size="sm" color="blue" variant="light" onClick={handlePromote} loading={loading}>
      Promote {(job.eval_score * 100).toFixed(1)}%
    </Button>
  );
}

export default function MLTrainingWorkbench() {
  const [workbench, setWorkbench] = useState<TrainingWorkbenchSnapshot | null>(null);
  const [datasets, setDatasets] = useState<{ training: TrainingDatasetEntry[]; dpo: TrainingDatasetEntry[] } | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [logs, setLogs] = useState<TrainingJobLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [startingJob, setStartingJob] = useState(false);
  const [cancellingJob, setCancellingJob] = useState(false);
  const [championRefreshKey, setChampionRefreshKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState<StartTrainingJobPayload>({
    mode: 'sft',
    base_model: 'google/gemma-3-12b-it',
    epochs: 3,
    learning_rate: 2e-4,
    batch_size: 1,
    grad_accum: 8,
    max_seq_len: 4096,
    lora_rank: 64,
    lora_alpha: 16,
    training_files: [],
    dpo_files: [],
    source_artifact: null,
    ollama_model: 'lex',
    max_per_cat: 20,
    deploy_to_ollama: true,
  });

  const refreshWorkbench = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const snapshot = await mlTrainingApi.getWorkbench();
      startTransition(() => {
        setWorkbench(snapshot);
        setError(null);
        setForm(prev => ({
          ...prev,
          base_model: snapshot.presets.base_models.includes(prev.base_model)
            ? prev.base_model
            : snapshot.presets.base_models[0] ?? prev.base_model,
        }));
        setSelectedJobId(prev => prev ?? snapshot.jobs[0]?.job_id ?? null);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load ML workbench');
    } finally {
      if (showSpinner) setRefreshing(false);
      setLoading(false);
    }
  }, []);

  const refreshDatasets = useCallback(async () => {
    const response = await mlTrainingApi.getDatasets();
    setDatasets(response);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        await Promise.all([refreshWorkbench(true), refreshDatasets()]);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load ML control data');
          setLoading(false);
        }
      }
    };

    void load();
    const interval = window.setInterval(() => {
      void refreshWorkbench();
    }, POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshDatasets, refreshWorkbench]);

  useEffect(() => {
    if (!selectedJobId) {
      setLogs(null);
      return;
    }

    let cancelled = false;

    const fetchLogs = async () => {
      try {
        const nextLogs = await mlTrainingApi.getJobLogs(selectedJobId, 180);
        if (!cancelled) setLogs(nextLogs);
      } catch (err) {
        if (!cancelled) {
          setActionError(err instanceof Error ? err.message : 'Failed to fetch job logs');
        }
      }
    };

    void fetchLogs();
    const interval = window.setInterval(() => {
      void fetchLogs();
    }, LOG_POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [selectedJobId]);

  const selectedJob = useMemo(
    () => workbench?.jobs.find(job => job.job_id === selectedJobId) ?? workbench?.jobs[0] ?? null,
    [selectedJobId, workbench?.jobs],
  );

  useEffect(() => {
    if (!datasets) return;

    setForm(prev => {
      let next = prev;
      const recommendedTraining = topRecommendedTraining(datasets.training);
      const recommendedDpo = topRecommendedDpo(datasets.dpo);

      if (prev.training_files.length === 0) {
        next = { ...next, training_files: recommendedTraining };
      }

      if ((prev.mode === 'dpo' || prev.mode === 'export') && !prev.source_artifact) {
        next = { ...next, source_artifact: workbench?.artifacts[0]?.path ?? null };
      }

      if (prev.mode === 'dpo' && prev.dpo_files.length === 0) {
        next = { ...next, dpo_files: recommendedDpo };
      }

      return next;
    });
  }, [datasets, workbench?.artifacts]);

  const artifactOptions = useMemo(() => toSelectData(workbench?.artifacts ?? []), [workbench?.artifacts]);
  const recommendedTraining = useMemo(() => topRecommendedTraining(datasets?.training ?? []), [datasets?.training]);
  const recommendedDpo = useMemo(() => topRecommendedDpo(datasets?.dpo ?? []), [datasets?.dpo]);

  const setNumberField = <K extends keyof StartTrainingJobPayload>(
    key: K,
    fallback: number,
  ) => (value: string | number) => {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      setForm(prev => ({ ...prev, [key]: fallback }));
      return;
    }
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const handleModeChange = (value: string | null) => {
    if (!value) return;
    const mode = value as StartTrainingJobPayload['mode'];
    setForm(prev => {
      let next: StartTrainingJobPayload = { ...prev, mode };
      if (mode === 'dpo' && prev.dpo_files.length === 0) {
        next = { ...next, dpo_files: recommendedDpo };
      }
      if ((mode === 'dpo' || mode === 'export') && !prev.source_artifact) {
        next = { ...next, source_artifact: workbench?.artifacts[0]?.path ?? null };
      }
      return next;
    });
  };

  const handleStartJob = async () => {
    setStartingJob(true);
    setActionError(null);
    try {
      const response = await mlTrainingApi.startJob(form);
      setSelectedJobId(response.job.job_id);
      await refreshWorkbench();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to start training job');
    } finally {
      setStartingJob(false);
    }
  };

  const handleCancelJob = async () => {
    if (!selectedJob) return;
    setCancellingJob(true);
    setActionError(null);
    try {
      await mlTrainingApi.cancelJob(selectedJob.job_id);
      await refreshWorkbench();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to cancel job');
    } finally {
      setCancellingJob(false);
    }
  };

  const handlePromoted = async () => {
    await refreshWorkbench();
    setChampionRefreshKey((prev) => prev + 1);
  };

  if (loading) {
    return (
      <Paper withBorder p="xl" radius="lg">
        <Group justify="center" py="xl">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading Lex training cockpit…
          </Text>
        </Group>
      </Paper>
    );
  }

  if (!workbench || !datasets) {
    return (
      <Paper withBorder p="xl" radius="lg">
        <Text size="sm" c="red">
          {error ?? 'ML control center unavailable'}
        </Text>
      </Paper>
    );
  }

  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, xl: 4 }}>
        <Card
          withBorder
          radius="lg"
          p="lg"
          style={{
            background:
              'linear-gradient(180deg, rgba(61,150,255,0.12) 0%, rgba(10,17,28,0.94) 28%, rgba(10,17,28,0.98) 100%)',
            borderColor: 'rgba(61,150,255,0.16)',
            position: 'sticky',
            top: 18,
          }}
        >
          <Stack gap="md">
            <Group justify="space-between" align="flex-start">
              <div>
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  Local Lex Training
                </Text>
                <Title order={3} style={{ letterSpacing: '-0.03em' }}>
                  Operator Rail
                </Title>
              </div>
              <Badge color="blue" variant="light">
                Unsloth-style
              </Badge>
            </Group>

            <Paper withBorder p="md" radius="md" style={{ background: 'rgba(0,0,0,0.18)' }}>
              <Stack gap="xs">
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  Preset
                </Text>
                <Select
                  size="sm"
                  value={form.mode}
                  onChange={handleModeChange}
                  data={workbench.presets.modes}
                />
                <Text size="xs" c="dimmed">
                  Curated modes only. The UI never exposes arbitrary shell execution.
                </Text>
              </Stack>
            </Paper>

            <Select
              label="Base model"
              size="sm"
              value={form.base_model}
              onChange={(value) => value && setForm(prev => ({ ...prev, base_model: value }))}
              data={workbench.presets.base_models}
              disabled={form.mode === 'dpo' || form.mode === 'export' || form.mode === 'native'}
            />

            {(form.mode === 'dpo' || form.mode === 'export') && (
              <Select
                label={form.mode === 'dpo' ? 'Source SFT checkpoint' : 'Source model artifact'}
                size="sm"
                searchable
                value={form.source_artifact}
                onChange={(value) => setForm(prev => ({ ...prev, source_artifact: value }))}
                data={artifactOptions}
                placeholder="Select a local artifact"
              />
            )}

            <SimpleGrid cols={2} spacing="sm">
              <NumberInput
                label="Epochs"
                size="sm"
                value={form.epochs}
                onChange={setNumberField('epochs', 3)}
                min={1}
                max={20}
                disabled={form.mode === 'dpo' || form.mode === 'export' || form.mode === 'native'}
              />
              <NumberInput
                label="Learning rate"
                size="sm"
                value={form.learning_rate}
                onChange={setNumberField('learning_rate', 2e-4)}
                min={0.000001}
                max={0.01}
                decimalScale={6}
                step={0.00005}
                disabled={form.mode === 'dpo' || form.mode === 'export' || form.mode === 'native'}
              />
              <NumberInput
                label="Batch size"
                size="sm"
                value={form.batch_size}
                onChange={setNumberField('batch_size', 1)}
                min={1}
                max={16}
              />
              <NumberInput
                label="Grad accum"
                size="sm"
                value={form.grad_accum}
                onChange={setNumberField('grad_accum', 8)}
                min={1}
                max={128}
              />
              <NumberInput
                label="Max seq len"
                size="sm"
                value={form.max_seq_len}
                onChange={setNumberField('max_seq_len', 4096)}
                min={256}
                max={16384}
                step={256}
              />
              <NumberInput
                label="LoRA rank"
                size="sm"
                value={form.lora_rank}
                onChange={setNumberField('lora_rank', 64)}
                min={4}
                max={512}
                step={4}
              />
              <NumberInput
                label="LoRA alpha"
                size="sm"
                value={form.lora_alpha}
                onChange={setNumberField('lora_alpha', 16)}
                min={4}
                max={512}
                step={4}
              />
              <NumberInput
                label="Native max/category"
                size="sm"
                value={form.max_per_cat}
                onChange={setNumberField('max_per_cat', 20)}
                min={1}
                max={100}
                disabled={form.mode !== 'native'}
              />
            </SimpleGrid>

            <Select
              label="Ollama target"
              size="sm"
              value={form.ollama_model}
              onChange={(value) => value && setForm(prev => ({ ...prev, ollama_model: value }))}
              data={Array.from(new Set([form.ollama_model, workbench.readiness.default_ollama_model, ...workbench.readiness.ollama.models])).filter(Boolean)}
            />

            <Switch
              checked={form.deploy_to_ollama}
              onChange={(event) => { const checked = event.currentTarget?.checked ?? !form.deploy_to_ollama; setForm(prev => ({ ...prev, deploy_to_ollama: checked })); }}
              label="Publish to Ollama at the end of the run"
            />

            <Divider label="Datasets" labelPosition="center" />

            {form.mode !== 'export' && (
              <DatasetPicker
                title="Training data"
                description="Choose the supervised dataset slice from data/training."
                items={datasets.training}
                selected={form.training_files}
                onChange={(training_files) => setForm(prev => ({ ...prev, training_files }))}
                recommendedNames={recommendedTraining}
              />
            )}

            {form.mode === 'dpo' && (
              <DatasetPicker
                title="DPO preferences"
                description="Choose preference pairs from data/dpo for alignment."
                items={datasets.dpo}
                selected={form.dpo_files}
                onChange={(dpo_files) => setForm(prev => ({ ...prev, dpo_files }))}
                recommendedNames={recommendedDpo}
              />
            )}

            <Group grow>
              <Button
                leftSection={<IconPlayerPlay size={16} />}
                onClick={handleStartJob}
                loading={startingJob}
                size="md"
                radius="md"
              >
                Launch job
              </Button>
              <Button
                variant="light"
                color="gray"
                leftSection={<IconRefresh size={16} />}
                onClick={() => void Promise.all([refreshWorkbench(true), refreshDatasets()])}
                loading={refreshing}
                size="md"
                radius="md"
              >
                Refresh
              </Button>
            </Group>

            {actionError && (
              <Text size="sm" c="red">
                {actionError}
              </Text>
            )}
          </Stack>
        </Card>
      </Grid.Col>

      <Grid.Col span={{ base: 12, xl: 8 }}>
        <Stack gap="lg">
          <Card
            withBorder
            radius="lg"
            p="lg"
            style={{
              background: 'linear-gradient(135deg, rgba(14,18,24,0.96) 0%, rgba(18,28,40,0.92) 100%)',
              borderColor: 'rgba(61,150,255,0.16)',
            }}
          >
            <Group justify="space-between" align="flex-start" mb="md">
              <Group justify="space-between" align="flex-start" style={{ flex: 1 }}>
                <div>
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Active lifecycle
                  </Text>
                  <Title order={3} style={{ letterSpacing: '-0.03em' }}>
                    Training cockpit
                  </Title>
                </div>
                {selectedJob ? (
                  <Group gap="xs">
                    <Badge color={statusColor(selectedJob.status)} size="lg">
                      {selectedJob.status}
                    </Badge>
                    <Badge variant="light" color="blue">
                      {stageLabel(selectedJob.current_stage)}
                    </Badge>
                  </Group>
                ) : (
                  <Badge variant="light" color="gray">
                    idle
                  </Badge>
                )}
              </Group>
              <ChampionBadge refreshKey={championRefreshKey} />
            </Group>

            <SimpleGrid cols={{ base: 1, md: 4 }} mb="md">
              <Paper withBorder p="md" radius="md">
                <Group justify="space-between">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Current job
                  </Text>
                  <IconTerminal2 size={16} />
                </Group>
                <Text fw={700} mt={6}>
                  {selectedJob?.job_id ?? 'No job selected'}
                </Text>
                <Text size="xs" c="dimmed">
                  {selectedJob ? fmt.time(selectedJob.started_at ?? selectedJob.created_at) : 'Start a run from the rail'}
                </Text>
              </Paper>

              <Paper withBorder p="md" radius="md">
                <Group justify="space-between">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Unsloth
                  </Text>
                  <IconBrain size={16} />
                </Group>
                <Text fw={700} mt={6}>
                  {workbench.readiness.unsloth.installed ? 'Installed' : 'Missing'}
                </Text>
                <Text size="xs" c="dimmed">
                  Python {workbench.readiness.python.version}
                </Text>
              </Paper>

              <Paper withBorder p="md" radius="md">
                <Group justify="space-between">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Ollama
                  </Text>
                  <IconBolt size={16} />
                </Group>
                <Text fw={700} mt={6}>
                  {workbench.readiness.ollama.reachable ? 'Reachable' : 'Offline'}
                </Text>
                <Text size="xs" c="dimmed">
                  Target: {form.ollama_model}
                </Text>
              </Paper>

              <Paper withBorder p="md" radius="md">
                <Group justify="space-between">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Hardware
                  </Text>
                  <IconCpu size={16} />
                </Group>
                <Text fw={700} mt={6}>
                  {workbench.readiness.gpu.available ? workbench.readiness.gpu.name : 'CPU only'}
                </Text>
                <Text size="xs" c="dimmed">
                  {workbench.readiness.gpu.available ? `${workbench.readiness.gpu.memory_gb} GB VRAM` : 'No CUDA GPU detected'}
                </Text>
              </Paper>
            </SimpleGrid>

            <Group gap="sm" mb="sm">
              <Button
                size="sm"
                variant="light"
                color="red"
                leftSection={<IconSquareRoundedX size={16} />}
                disabled={!selectedJob || (selectedJob.status !== 'running' && selectedJob.status !== 'cancelling')}
                loading={cancellingJob}
                onClick={handleCancelJob}
              >
                Cancel selected job
              </Button>
              {selectedJob && (
                <PromoteButton
                  job={selectedJob}
                  onPromoted={handlePromoted}
                  onError={(message) => setActionError(message)}
                />
              )}
              {selectedJob && (
                <Text size="sm" c="dimmed">
                  PID {selectedJob.pid ?? '—'} • mode {selectedJob.mode}
                  {selectedJob.eval_score == null
                    ? ''
                    : ` • eval ${(selectedJob.eval_score * 100).toFixed(1)}% (${selectedJob.eval_n ?? 0})`}
                </Text>
              )}
            </Group>

            <Code block style={{ whiteSpace: 'pre-wrap' }}>
              {selectedJob?.command.join(' ') ?? 'No active command'}
            </Code>
          </Card>

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <Card withBorder radius="lg" p="lg" h="100%">
                <Group justify="space-between" mb="sm">
                  <div>
                    <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                      Live log tail
                    </Text>
                    <Title order={4}>Operator console</Title>
                  </div>
                  <Group gap={6}>
                    {logs && (
                      <Badge variant="light" color={statusColor((logs.status as TrainingJob['status']) || 'completed')}>
                        {stageLabel(logs.current_stage)}
                      </Badge>
                    )}
                    <CopyLogButton text={logs?.text ?? ''} />
                  </Group>
                </Group>
                <ScrollArea h={520} offsetScrollbars>
                  <Code block style={{ minHeight: 480, whiteSpace: 'pre-wrap', background: '#0c1117' }}>
                    {logs?.text || 'Select or start a job to stream local training logs here.'}
                  </Code>
                </ScrollArea>
              </Card>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 5 }}>
              <Stack gap="lg">
                <MetricsChart activeJob={selectedJob} />

                <Card withBorder radius="lg" p="lg">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Learning lab coverage
                  </Text>
                  <Title order={4} mb="sm">
                    Golden tasks and boundaries
                  </Title>
                  <SimpleGrid cols={2} mb="md">
                    <Paper withBorder p="md" radius="md">
                      <Text size="xs" c="dimmed">
                        Golden tasks
                      </Text>
                      <Text size="xl" fw={700}>
                        {fmt.num(workbench.golden_coverage.total_tasks)}
                      </Text>
                    </Paper>
                    <Paper withBorder p="md" radius="md">
                      <Text size="xs" c="dimmed">
                        Boundary pairs
                      </Text>
                      <Text size="xl" fw={700}>
                        {fmt.num(workbench.boundary_coverage.total_boundaries)}
                      </Text>
                    </Paper>
                  </SimpleGrid>

                  <Text size="xs" c="dimmed" mb={6}>
                    Difficulty mix
                  </Text>
                  <Group gap={6} mb="md">
                    {Object.entries(workbench.golden_coverage.by_difficulty).map(([label, count]) => (
                      <Badge key={label} variant="light" color="yellow">
                        {label}: {count}
                      </Badge>
                    ))}
                  </Group>

                  <Text size="xs" c="dimmed" mb={6}>
                    Top weak boundaries
                  </Text>
                  <Stack gap={8}>
                    {workbench.boundary_coverage.top_boundaries.map(item => (
                      <Paper key={item.boundary} withBorder p="sm" radius="md">
                        <Group justify="space-between" mb={4}>
                          <Text size="xs" fw={600}>
                            {item.boundary}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {item.count}
                          </Text>
                        </Group>
                        <Progress
                          value={Math.min(100, item.count)}
                          color={item.count >= 10 ? 'green' : item.count >= 5 ? 'yellow' : 'red'}
                          size="sm"
                        />
                      </Paper>
                    ))}
                  </Stack>
                </Card>

                <Card withBorder radius="lg" p="lg">
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Readiness notes
                  </Text>
                  <Title order={4} mb="sm">
                    Lab signals
                  </Title>
                  <Text size="sm" mb="sm">
                    Routing accuracy: {workbench.lab_health.routing_accuracy == null ? '—' : fmt.pct(workbench.lab_health.routing_accuracy)}
                  </Text>
                  <Text size="sm" mb="md">
                    Dataset inventory: {fmt.num(workbench.dataset_selection_summary.training_lines)} SFT lines and {fmt.num(workbench.dataset_selection_summary.dpo_lines)} DPO lines available.
                  </Text>
                  <Stack gap="xs">
                    {workbench.lab_health.recommendations.slice(0, 4).map((note) => (
                      <Paper key={note} withBorder p="sm" radius="md">
                        <Text size="xs" c="dimmed">
                          {note}
                        </Text>
                      </Paper>
                    ))}
                    {workbench.lab_health.recommendations.length === 0 && (
                      <Text size="xs" c="dimmed">
                        No immediate readiness blockers reported by the learning lab.
                      </Text>
                    )}
                  </Stack>
                </Card>
              </Stack>
            </Grid.Col>
          </Grid>

          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 6 }}>
              <Card withBorder radius="lg" p="lg" h="100%">
                <Group justify="space-between" mb="sm">
                  <div>
                    <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                      Recent experiments
                    </Text>
                    <Title order={4}>Finetune runs</Title>
                  </div>
                  <Badge variant="light" color="blue">
                    {workbench.recent_experiments.length}
                  </Badge>
                </Group>
                <ScrollArea h={260} offsetScrollbars>
                  <Stack gap="sm">
                    {workbench.recent_experiments.map((run) => (
                      <Paper key={run.run_id} withBorder p="sm" radius="md">
                        <Group justify="space-between" mb={4}>
                          <Text size="sm" fw={700}>
                            {run.run_id}
                          </Text>
                          <Badge color={run.status === 'completed' ? 'green' : run.status === 'failed' ? 'red' : 'yellow'}>
                            {run.status}
                          </Badge>
                        </Group>
                        <Text size="xs" c="dimmed">
                          {fmt.time(run.started_at)}
                        </Text>
                        <Text size="xs" mt={4}>
                          Base model: {String(run.tags?.base_model ?? run.hyperparameters?.base_model ?? 'n/a')}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Artifacts: {run.artifacts.length}
                        </Text>
                      </Paper>
                    ))}
                    {workbench.recent_experiments.length === 0 && (
                      <Text size="sm" c="dimmed" ta="center" py="lg">
                        No Lex finetune experiments recorded yet.
                      </Text>
                    )}
                  </Stack>
                </ScrollArea>
              </Card>
            </Grid.Col>

            <Grid.Col span={{ base: 12, lg: 6 }}>
              <Card withBorder radius="lg" p="lg" h="100%">
                <Group justify="space-between" mb="sm">
                  <div>
                    <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                      Eval outcomes
                    </Text>
                    <Title order={4}>Recent signals</Title>
                  </div>
                  <Badge variant="light" color="green">
                    {fmt.pct(workbench.eval_summary.pass_rate)}
                  </Badge>
                </Group>

                <Stack gap="xs" mb="md">
                  {Object.entries(workbench.eval_summary.by_dimension).slice(0, 4).map(([dimension, score]) => (
                    <Box key={dimension}>
                      <Group justify="space-between" mb={4}>
                        <Text size="xs" tt="capitalize">
                          {dimension.replace(/_/g, ' ')}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {fmt.pct(score)}
                        </Text>
                      </Group>
                      <Progress value={score * 100} color={score >= 0.8 ? 'green' : score >= 0.6 ? 'yellow' : 'red'} size="sm" />
                    </Box>
                  ))}
                </Stack>

                <ScrollArea h={210} offsetScrollbars>
                  <Stack gap="sm">
                    {workbench.recent_evals.map((item) => (
                      <Paper key={`${item.case_id}-${item.timestamp}`} withBorder p="sm" radius="md">
                        <Group justify="space-between" mb={4}>
                          <Text size="xs" fw={700}>
                            {item.case_id}
                          </Text>
                          <Badge color={item.passed ? 'green' : 'red'}>
                            {item.passed ? 'PASS' : 'FAIL'}
                          </Badge>
                        </Group>
                        <Text size="xs">{item.model}</Text>
                        <Text size="xs" c="dimmed">
                          {item.task_type} • {(item.overall_score * 100).toFixed(0)}% • {fmt.time(item.timestamp)}
                        </Text>
                      </Paper>
                    ))}
                    {workbench.recent_evals.length === 0 && (
                      <Text size="sm" c="dimmed" ta="center" py="lg">
                        No persisted eval results yet.
                      </Text>
                    )}
                  </Stack>
                </ScrollArea>
              </Card>
            </Grid.Col>
          </Grid>

          {workbench.jobs.length > 0 && (
            <Card withBorder radius="lg" p="lg">
              <Group justify="space-between" mb="sm">
                <div>
                  <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                    Queue view
                  </Text>
                  <Title order={4}>Recent local jobs</Title>
                </div>
                <Badge variant="light" color="blue">
                  {workbench.jobs.length}
                </Badge>
              </Group>
              <ScrollArea h={180} offsetScrollbars>
                <Stack gap="sm">
                  {workbench.jobs.map((job) => (
                    <Paper
                      key={job.job_id}
                      withBorder
                      p="sm"
                      radius="md"
                      onClick={() => setSelectedJobId(job.job_id)}
                      style={{
                        cursor: 'pointer',
                        background: selectedJobId === job.job_id ? 'rgba(61,150,255,0.10)' : undefined,
                        borderColor: selectedJobId === job.job_id ? 'rgba(61,150,255,0.28)' : undefined,
                      }}
                    >
                      <Group justify="space-between" align="center">
                        <div>
                          <Text size="sm" fw={700}>
                            {job.job_id}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {job.mode} • {stageLabel(job.current_stage)} • {fmt.time(job.created_at)}
                          </Text>
                        </div>
                        <Badge color={statusColor(job.status)}>{job.status}</Badge>
                      </Group>
                    </Paper>
                  ))}
                </Stack>
              </ScrollArea>
            </Card>
          )}

          {(error || actionError) && (
            <Paper withBorder p="md" radius="lg" style={{ borderColor: 'rgba(255, 99, 99, 0.35)' }}>
              <Text size="sm" c="red">
                {actionError ?? error}
              </Text>
            </Paper>
          )}
        </Stack>
      </Grid.Col>
    </Grid>
  );
}
