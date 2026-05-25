import { API_BASE } from '@/lib/api';

export interface TrainingDatasetEntry {
  name: string;
  kind: 'training' | 'dpo';
  size_bytes: number;
  line_count: number;
  modified_at: string;
}

export interface TrainingArtifactEntry {
  name: string;
  label: string;
  kind: string;
  path: string;
  modified_at: string;
}

export interface TrainingJob {
  job_id: string;
  mode: 'prep-only' | 'sft' | 'dpo' | 'export' | 'native';
  status: 'running' | 'completed' | 'failed' | 'cancelling' | 'cancelled';
  created_at: string;
  base_model: string;
  epochs: number;
  learning_rate: number;
  batch_size: number;
  grad_accum: number;
  max_seq_len: number;
  lora_rank: number;
  lora_alpha: number;
  ollama_model: string;
  training_files: string[];
  dpo_files: string[];
  source_artifact: string | null;
  max_per_cat: number;
  deploy_to_ollama: boolean;
  current_stage: string;
  started_at: string | null;
  finished_at: string | null;
  pid: number | null;
  returncode: number | null;
  error: string | null;
  log_path: string;
  output_dir: string;
  command: string[];
  updated_at: string;
  eval_score: number | null;
  eval_n: number | null;
}

export interface ChampionStatus {
  model: string;
  score: number | null;
  promoted_at: string | null;
}

export interface TrainingMetricPoint {
  step: number;
  loss: number;
  accuracy: number;
  ts: string;
}

export interface TrainingWorkbenchSnapshot {
  readiness: {
    finetune_script: { exists: boolean; path: string };
    python: { executable: string; version: string };
    unsloth: { installed: boolean };
    ollama: { reachable: boolean; base_url: string; models: string[] };
    gpu: { available: boolean; name: string; memory_gb: number };
    default_ollama_model: string;
    base_model_options: string[];
  };
  artifacts: TrainingArtifactEntry[];
  jobs: TrainingJob[];
  lab_health: {
    timestamp: string;
    models_available: string[];
    golden_tasks_count: number;
    routing_accuracy: number | null;
    recommendations: string[];
    dataset_stats: {
      routing_files: number;
      trajectory_files: number;
      dpo_files: number;
      total_routing_pairs: number;
      total_trajectory_pairs: number;
      total_dpo_pairs: number;
      latest_file: string;
      latest_timestamp: string;
    };
  };
  golden_coverage: {
    total_tasks: number;
    by_difficulty: Record<string, number>;
  };
  boundary_coverage: {
    total_boundaries: number;
    top_boundaries: Array<{ boundary: string; count: number }>;
  };
  dataset_selection_summary: {
    training_files: number;
    training_lines: number;
    dpo_files: number;
    dpo_lines: number;
  };
  dataset_file_snapshot: {
    total_files: number;
    top_files: Array<{ name: string; line_count: number }>;
  };
  eval_summary: {
    total_cases: number;
    avg_score: number;
    pass_rate: number;
    by_dimension: Record<string, number>;
  };
  recent_evals: Array<{
    case_id: string;
    task_type: string;
    model: string;
    overall_score: number;
    passed: boolean;
    timestamp: string;
  }>;
  recent_experiments: Array<{
    run_id: string;
    experiment_name: string;
    status: string;
    started_at: string;
    ended_at: string | null;
    hyperparameters: Record<string, unknown>;
    tags: Record<string, string>;
    artifacts: string[];
    notes: string;
  }>;
  presets: {
    modes: Array<{ value: string; label: string }>;
    base_models: string[];
  };
}

export interface TrainingJobLogResponse {
  job_id: string;
  tail: number;
  lines: string[];
  text: string;
  current_stage: string;
  status: string;
}

export interface StartTrainingJobPayload {
  mode: 'prep-only' | 'sft' | 'dpo' | 'export' | 'native';
  base_model: string;
  epochs: number;
  learning_rate: number;
  batch_size: number;
  grad_accum: number;
  max_seq_len: number;
  lora_rank: number;
  lora_alpha: number;
  training_files: string[];
  dpo_files: string[];
  source_artifact: string | null;
  ollama_model: string;
  max_per_cat: number;
  deploy_to_ollama: boolean;
}

interface DatasetCatalogResponse {
  training: TrainingDatasetEntry[];
  dpo: TrainingDatasetEntry[];
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail);
      }
    } catch {
      // Fall back to the HTTP status line.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export const mlTrainingApi = {
  getWorkbench: () => fetchJson<TrainingWorkbenchSnapshot>('/api/ml/training/workbench'),
  getDatasets: () => fetchJson<DatasetCatalogResponse>('/api/ml/training/datasets'),
  getArtifacts: () => fetchJson<{ artifacts: TrainingArtifactEntry[] }>('/api/ml/training/artifacts'),
  getChampion: () => fetchJson<ChampionStatus>('/api/ml/training/champion'),
  startJob: (payload: StartTrainingJobPayload) =>
    fetchJson<{ job: TrainingJob }>('/api/ml/training/jobs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getJob: (jobId: string) => fetchJson<{ job: TrainingJob }>(`/api/ml/training/jobs/${encodeURIComponent(jobId)}`),
  getJobLogs: (jobId: string, tail = 200) =>
    fetchJson<TrainingJobLogResponse>(`/api/ml/training/jobs/${encodeURIComponent(jobId)}/logs?tail=${tail}`),
  cancelJob: (jobId: string) =>
    fetchJson<{ job: TrainingJob }>(`/api/ml/training/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    }),
  promoteJob: (jobId: string) =>
    fetchJson<{ champion: ChampionStatus; job_id: string; model_name: string }>(
      `/api/ml/training/jobs/${encodeURIComponent(jobId)}/promote`,
      {
        method: 'POST',
      },
    ),
  subscribeMetrics: (
    jobId: string,
    onData: (point: TrainingMetricPoint) => void,
    onDone: (status: string) => void,
  ) => {
    const source = new EventSource(`${API_BASE}/api/ml/training/jobs/${encodeURIComponent(jobId)}/metrics`);
    let closed = false;

    const close = () => {
      if (closed) return;
      closed = true;
      source.close();
    };

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as TrainingMetricPoint;
        onData(payload);
      } catch {
        // Ignore malformed metric rows from partial writes.
      }
    };

    source.addEventListener('done', (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as { status?: string };
        onDone(payload.status ?? 'completed');
      } finally {
        close();
      }
    });

    source.onerror = () => {
      onDone('disconnected');
      close();
    };

    return close;
  },
};
