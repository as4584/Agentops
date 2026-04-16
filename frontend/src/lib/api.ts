/**
 * API Client — Communicates with the Agentop FastAPI backend.
 *
 * The dashboard is READ-ONLY (INV-8) — it reads state from the backend
 * and can only send messages through the sanctioned /chat endpoint.
 * No direct backend mutation.
 */

// In the browser, always use the Next.js proxy so we avoid direct cross-origin
// backend calls and keep auth/header handling on the server side.
export const API_BASE =
  typeof window === 'undefined'
    ? process.env.NEXT_PUBLIC_API_URL || '/api/proxy'
    : '/api/proxy';

export interface AgentDefinition {
  agent_id: string;
  role: string;
  system_prompt: string;
  tool_permissions: string[];
  memory_namespace: string;
  allowed_actions: string[];
  change_impact_level: string;
}

export interface AgentState {
  agent_id: string;
  status: string;
  last_active: string | null;
  memory_size_bytes: number;
  total_actions: number;
  error_count: number;
}

export interface ToolDefinition {
  name: string;
  description: string;
  modification_type: string;
  requires_doc_update: boolean;
}

export interface DriftReport {
  status: 'GREEN' | 'YELLOW' | 'RED';
  pending_updates: string[];
  violations: DriftEvent[];
  last_check: string;
}

export interface DriftEvent {
  timestamp: string;
  invariant_id: string;
  description: string;
  severity: string;
  resolved: boolean;
}

export interface ToolLog {
  timestamp: string;
  tool_name: string;
  agent_id: string;
  modification_type: string;
  input_summary: string;
  output_summary: string;
  success: boolean;
  error: string | null;
  doc_updated: boolean;
}

export interface SystemStatus {
  agents: AgentState[];
  drift_report: DriftReport;
  recent_logs: ToolLog[];
  total_tool_executions: number;
  uptime_seconds: number;
}

export interface ChatResponse {
  agent_id: string;
  message: string;
  drift_status: string;
  timestamp: string;
}

export interface HealthCheck {
  status: string;
  llm_available: boolean;
  drift_status: string;
  uptime_seconds: number;
  timestamp: string;
}

export interface KnowledgeReindexResponse {
  success: boolean;
  message: string;
  agent_id: string;
  chunks: number;
  index_size_bytes: number;
  index_size_mb: number;
}

export interface AgentMemoryUsage {
  agent_id: string;
  namespace: string;
  size_bytes: number;
  size_mb: number;
}

export interface IntakeStartResponse {
  business_id: string;
  current_question_index: number;
  total_questions: number;
  question_key: string;
  question: string;
  completed: boolean;
}

export interface IntakeStatusResponse {
  business_id: string;
  current_question_index: number;
  total_questions: number;
  completed: boolean;
  next_question_key: string | null;
  next_question: string | null;
  answers: Record<string, string>;
}

export interface CampaignGenerateRequest {
  business_id: string;
  platform: string;
  objective: string;
  format_type?: string;
  duration_seconds?: number;
}

export interface CampaignGenerateResponse {
  business_id: string;
  platform: string;
  objective: string;
  format_type: string;
  duration_seconds: number;
  generated_at: string;
  campaign: {
    script: string;
    caption: string;
    hashtags: string[];
    image_prompts: string[];
    shot_list: string[];
    cta: string;
  };
}

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const baseHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...baseHeaders,
      ...(options?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export interface SoulGoal {
  id: string;
  title: string;
  description: string;
  priority: string;
  created_at: string;
  completed: boolean;
  completed_at?: string;
}

export interface SoulReflection {
  reflection: string;
  trigger: string;
  timestamp: string;
}

export interface TaskItem {
  id: string;
  agent_id: string;
  action: string;
  detail: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error: string | null;
}

export interface TaskStats {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
}

export interface AgentVisualSnapshot {
  agent_id: string;
  visual_state: string;
  visual_detail: string;
}

export interface LLMModel {
  model_id: string;
  family: string;
  parameters: string;
  vram_gb: number;
  context_window: number;
  speed_tier: string;
  quality_tier: string;
  code_score: number;
  reasoning_score: number;
  instruction_score: number;
  multilingual_score: number;
  creative_score: number;
  best_for: string[];
  ollama_pull: string;
}

// Folder analysis types
export interface FolderEntry {
  name: string;
  is_dir: boolean;
  size_bytes: number | null;
  path: string;
}

export interface FolderBrowseResponse {
  current: string;
  parent: string | null;
  entries: FolderEntry[];
}

export interface FileAnalysis {
  path: string;
  name: string;
  extension: string;
  size_bytes: number;
  is_text: boolean;
  line_count: number | null;
  content_snippet: string | null;
}

export interface FolderAnalysis {
  folder: string;
  file_count: number;
  dir_count: number;
  total_size_bytes: number;
  total_size_mb: number;
  extension_summary: Record<string, number>;
  tree: string;
  files: FileAnalysis[];
  truncated: boolean;
}

export interface FolderAnalyzeResponse {
  analysis: FolderAnalysis;
  agent_response?: string;
}

// Live activity SSE event types
export interface ActivitySSEEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: string;
}

// LLM Stats types
export interface LLMStats {
  stats: {
    total_requests: number;
    local_requests: number;
    cloud_requests: number;
    tokens_in: number;
    tokens_out: number;
    estimated_cost_usd: number;
    avg_latency_ms: number;
    cost_per_request_avg: number;
  };
  cost_log: {
    timestamp: string;
    destination: string;
    model: string;
    task: string;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
    cost_usd: number;
  }[];
  budget: {
    monthly_limit_usd: number;
    spent_usd: number;
    remaining_usd: number;
    percent_used: number;
  };
  tokens: {
    total_in: number;
    total_out: number;
    total: number;
  };
  circuit_states?: Record<string, {
    model_id: string;
    healthy: boolean;
    circuit_open: boolean;
    consecutive_failures: number;
    last_error: string | null;
  }>;
}

export interface ModelCircuitState {
  model_id: string;
  healthy: boolean;
  circuit_open: boolean;
  consecutive_failures: number;
  last_error: string | null;
}

export interface LLMHealthData {
  circuit_states: Record<string, ModelCircuitState>;
}

export interface ModelCapacity {
  model_id: string;
  family: string;
  parameters: string;
  vram_gb: number;
  context_window: number;
  speed_tier: string;
  quality_tier: string;
  available: boolean;
  estimated_tokens_per_second: number;
  best_for: string[];
  provider?: 'local' | 'cloud';
  cost_per_m_in?: number;
  cost_per_m_out?: number;
}

export interface LLMCapacity {
  available_models: string[];
  total_known_models: number;
  model_capacities: ModelCapacity[];
}

export interface LLMEstimate {
  prompt_tokens: number;
  max_tokens: number;
  estimates: {
    model_id: string;
    estimated_tps: number;
    estimated_seconds: number;
    estimated_time_human: string;
    fits_context: boolean;
    context_window: number;
  }[];
}

export interface ProjectEntry {
  id: string;
  name: string;
  type: string;
  path: string;
  file_count?: number;
  total_size_bytes?: number;
  total_size_mb?: number;
  status?: string;
  platform_targets?: string[];
  pages?: number;
  created_at: string;
  modified_at: string;
  /** Local preview URL served by the backend (e.g. http://localhost:8000/preview/{slug}/index.html) */
  preview_url?: string;
  /** Vercel deployed URL if the site has been deployed */
  deployed_url?: string;
  /** Output directory slug — the leaf folder name under output/webgen/ */
  webgen_dir?: string;
}

export interface ProjectsResponse {
  projects: ProjectEntry[];
  total: number;
  types: Record<string, number>;
}

export interface ProjectFilesResponse {
  project_id: string;
  project_type: string;
  files: { name: string; path: string; size_bytes: number; extension: string }[];
  file_count: number;
}

export interface WebgenGenerateResponse {
  project_id: string;
  project_slug: string;
  status: string;
  output_dir: string;
  preview_file: string;
  html: string;
  pages: string[];
}

export interface WebgenProjectItem {
  id: string;
  business_name: string;
  status: string;
  updated_at: string;
  output_dir: string;
}

export interface CustomerService {
  id: string;
  type: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  progress_percent: number;
  assigned_agents: string[];
}

export interface ServiceTimelineEvent {
  id: string;
  event_type: string;
  detail: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface CustomerRecord {
  id: string;
  name: string;
  email: string;
  business_name: string;
  tier: 'foundation' | 'growth' | 'domination';
  website_url: string | null;
  social_media_accounts: Record<string, string>;
  monthly_token_budget: number;
  tokens_used_this_month: number;
  services: CustomerService[];
}

export interface CustomerDeployment {
  id: string;
  customer_id: string;
  project_id: string;
  project_slug: string;
  deployed_url: string;
  qr_path: string | null;
  deployed_at: string;
  metadata: Record<string, unknown>;
}

export const api = {
  health: () => fetchAPI<HealthCheck>('/health'),
  status: () => fetchAPI<SystemStatus>('/status'),
  agents: () => fetchAPI<AgentDefinition[]>('/agents'),
  agent: (id: string) => fetchAPI<{ definition: AgentDefinition; state: AgentState }>(`/agents/${id}`),
  reindexKnowledge: () => fetchAPI<KnowledgeReindexResponse>('/knowledge/reindex', { method: 'POST' }),
  intakeStart: (businessId: string) =>
    fetchAPI<IntakeStartResponse>('/intake/start', {
      method: 'POST',
      body: JSON.stringify({ business_id: businessId }),
    }),
  intakeAnswer: (businessId: string, answer: string) =>
    fetchAPI<IntakeStatusResponse>('/intake/answer', {
      method: 'POST',
      body: JSON.stringify({ business_id: businessId, answer }),
    }),
  intakeStatus: (businessId: string) => fetchAPI<IntakeStatusResponse>(`/intake/${businessId}`),
  campaignGenerate: (request: CampaignGenerateRequest) =>
    fetchAPI<CampaignGenerateResponse>('/campaign/generate', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  tools: () => fetchAPI<ToolDefinition[]>('/tools'),
  drift: () => fetchAPI<DriftReport>('/drift'),
  driftEvents: () => fetchAPI<DriftEvent[]>('/drift/events'),
  logs: (limit = 50) => fetchAPI<ToolLog[]>(`/logs?limit=${limit}`),
  generalLogs: (limit = 100) => fetchAPI<Record<string, unknown>[]>(`/logs/general?limit=${limit}`),
  memory: () => fetchAPI<{ namespaces: Record<string, { size_bytes: number; size_mb: number }>; shared_events_count: number }>('/memory'),
  memoryAgents: () => fetchAPI<{ agents: AgentMemoryUsage[]; total_size_bytes: number; total_size_mb: number }>('/memory/agents'),
  memoryNamespace: (ns: string) => fetchAPI<{ namespace: string; data: Record<string, unknown>; size_bytes: number; size_mb: number }>(`/memory/${ns}`),
  events: (limit = 50) => fetchAPI<Record<string, unknown>[]>(`/events?limit=${limit}`),
  chat: (agentId: string, message: string) =>
    fetchAPI<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId, message }),
    }),
  // Soul endpoints
  soulReflect: (trigger = 'manual') =>
    fetchAPI<SoulReflection>(`/soul/reflect?trigger=${encodeURIComponent(trigger)}`, { method: 'POST' }),
  soulGoals: () => fetchAPI<{ goals: SoulGoal[]; count: number }>('/soul/goals'),
  soulAddGoal: (title: string, description: string, priority = 'MEDIUM') =>
    fetchAPI<SoulGoal>('/soul/goals', {
      method: 'POST',
      body: JSON.stringify({ title, description, priority }),
    }),
  // Task activity
  tasks: (limit = 50) =>
    fetchAPI<{ tasks: TaskItem[]; stats: TaskStats }>(`/tasks?limit=${limit}`),
  // LLM model knowledge
  models: () =>
    fetchAPI<{ models: LLMModel[]; available_locally: string[]; total_known: number; agent_recommendations: Record<string, any[]> }>('/models'),
  // Folder analysis
  browseFolders: (path = '.') =>
    fetchAPI<FolderBrowseResponse>(`/folders/browse?path=${encodeURIComponent(path)}`),
  analyzeFolder: (folderPath: string, agentId?: string, maxFiles = 200) =>
    fetchAPI<FolderAnalyzeResponse>('/folders/analyze', {
      method: 'POST',
      body: JSON.stringify({ folder_path: folderPath, agent_id: agentId, max_files: maxFiles }),
    }),
  // LLM stats & capacity
  llmStats: () => fetchAPI<LLMStats>('/llm/stats'),
  llmHealth: () => fetchAPI<LLMHealthData>('/llm/stats'),
  llmCapacity: () => fetchAPI<LLMCapacity>('/llm/capacity'),
  llmEstimate: (promptTokens = 500, maxTokens = 2048) =>
    fetchAPI<LLMEstimate>(`/llm/estimate?prompt_tokens=${promptTokens}&max_tokens=${maxTokens}`),
  // Projects
  projects: () => fetchAPI<ProjectsResponse>('/projects'),
  projectFiles: (projectId: string, projectType = 'webgen') =>
    fetchAPI<ProjectFilesResponse>(`/projects/${projectId}/files?project_type=${projectType}`),
  projectFileContent: (projectId: string, filePath: string, projectType = 'webgen') =>
    fetchAPI<{ content: string; path: string; size_bytes: number }>(
      `/projects/${projectId}/files/content?path=${encodeURIComponent(filePath)}&project_type=${projectType}`
    ),
  // Customer operations
  customers: () => fetchAPI<CustomerRecord[]>('/api/customers/'),
  customer: (id: string) => fetchAPI<CustomerRecord>(`/api/customers/${id}`),
  createCustomer: (payload: { name: string; email: string; business_name: string; tier: string }) =>
    fetchAPI<CustomerRecord>('/api/customers/', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  addCustomerService: (customerId: string, serviceType: string, notes = '') =>
    fetchAPI<{ service_id: string; status: string; assigned_agents: string[]; child_tasks: Record<string, string> }>(`/api/customers/${customerId}/services`, {
      method: 'POST',
      body: JSON.stringify({ service_type: serviceType, notes }),
    }),
  customerServiceTimeline: (customerId: string, serviceId: string) =>
    fetchAPI<{ customer_id: string; service_id: string; events: ServiceTimelineEvent[] }>(
      `/api/customers/${customerId}/services/${serviceId}/timeline`
    ),
  customerDashboardStats: () => fetchAPI<{ total_customers: number; active_services: number; total_tokens_used: number }>('/api/customers/dashboard/stats'),
  customerDeployments: (customerId: string) =>
    fetchAPI<{ customer_id: string; deployments: CustomerDeployment[]; count: number }>(`/api/customers/${customerId}/deployments`),
  // Webgen builder
  webgenGenerate: (payload: {
    business_name: string;
    business_type: string;
    tagline?: string;
    description?: string;
    services?: string[];
    target_audience?: string;
    tone?: string;
    customer_id?: string;
  }) =>
    fetchAPI<WebgenGenerateResponse>('/api/webgen/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  webgenProjects: () => fetchAPI<{ projects: WebgenProjectItem[]; count: number }>('/api/webgen/projects'),
  webgenProject: (projectId: string) =>
    fetchAPI<{ project_id: string; status: string; business_name: string; project_slug: string; preview_file: string; output_dir: string; html: string; deployed_url: string }>(
      `/api/webgen/projects/${projectId}`
    ),
  webgenSavePage: (projectId: string, html: string) =>
    fetchAPI<{ project_id: string; saved_file: string; status: string }>(`/api/webgen/projects/${projectId}/page`, {
      method: 'PUT',
      body: JSON.stringify({ html }),
    }),
  webgenDeploy: (projectId: string, customerId?: string) =>
    fetchAPI<{ project_id: string; deployed_url: string; status: string; customer_id?: string; qr_path?: string | null }>('/api/webgen/deploy', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, customer_id: customerId || null }),
    }),
  webgenQR: (projectId: string, targetUrl: string) =>
    fetchAPI<{ project_id: string; target_url: string; qr_path: string }>('/api/webgen/qr', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, target_url: targetUrl }),
    }),
  webgenQrFileUrl: (qrPath: string) => `${API_BASE}/api/webgen/qr/file?path=${encodeURIComponent(qrPath)}`,

  webgenReview: (payload: {
    project_id: string;
    business_slug: string;
    overall_score: number;
    visual_quality: number;
    clarity: number;
    conversion_strength: number;
    mobile_confidence: number;
    pass_fail: boolean;
    notes: string;
  }) =>
    fetchAPI<{ status: string; file: string }>('/ml/webgen/review', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ML Eval
  mlEvalSummary: (taskType?: string, model?: string) =>
    fetchAPI<{ total_cases: number; avg_score: number; pass_rate: number; by_dimension: Record<string, number>; by_model: Record<string, unknown> }>(
      `/ml/eval/summary${taskType || model ? '?' : ''}${taskType ? `task_type=${taskType}` : ''}${model ? `${taskType ? '&' : ''}model=${model}` : ''}`
    ),
  mlEvalResults: (limit = 20) =>
    fetchAPI<Array<{ case_id: string; task_type: string; model: string; score: number; pass_fail: boolean; timestamp: string }>>(`/ml/eval/results?limit=${limit}`),
  mlAbExperiments: () =>
    fetchAPI<Array<{ experiment_id: string; name: string; status: string; variants: unknown[] }>>('/ml/eval/ab'),
  mlGoldenTasks: () =>
    fetchAPI<Array<{ task_id: string; task_type: string; description: string; difficulty: string }>>('/ml/eval/golden'),
  mlTrainingFiles: () =>
    fetchAPI<{ files: Array<{ name: string; size_bytes: number; line_count: number }>; total_files: number; total_lines: number }>('/api/ml/training/files'),
  visualStates: () =>
    fetchAPI<AgentVisualSnapshot[]>('/api/agents/visual'),
};
