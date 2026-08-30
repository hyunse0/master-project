const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface CostAggregate {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  call_count: number
  run_count: number
  avg_tokens_per_run: number
}

export interface SchemaRagModeGroup extends CostAggregate {
  schema_rag_mode: string | null
}

export interface DifficultyModelGroup extends CostAggregate {
  difficulty: string | null
  model: string
}

export interface CostSummary<G> {
  group_by: string
  domain: string | null
  since: string | null
  overall: CostAggregate
  groups: G[]
}

export interface RecentRun {
  run_id: string
  question: string
  difficulty: string | null
  created_at: string
  total_tokens: number
}

export interface RunCostCall {
  node: string
  model: string
  input_tokens: number
  output_tokens: number
  tags: Record<string, unknown>
  created_at: string
}

export interface RunCostByNode {
  node: string
  model: string
  calls: number
  tokens: number
}

export interface RunCostDetail {
  run_id: string
  calls: RunCostCall[]
  by_node: RunCostByNode[]
  call_count: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(`${path} 요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') usp.set(key, String(value))
  }
  const qs = usp.toString()
  return qs ? `?${qs}` : ''
}

export const costApi = {
  schemaRagSummary: (params: { domain?: string; since?: string } = {}) =>
    getJSON<CostSummary<SchemaRagModeGroup>>(
      `/cost/summary${buildQuery({ group_by: 'schema_rag_mode', ...params })}`,
    ),

  difficultySummary: (params: { domain?: string; since?: string } = {}) =>
    getJSON<CostSummary<DifficultyModelGroup>>(
      `/cost/summary${buildQuery({ group_by: 'difficulty', ...params })}`,
    ),

  recentRuns: (params: { domain?: string; limit?: number } = {}) =>
    getJSON<{ runs: RecentRun[] }>(`/cost/recent-runs${buildQuery(params)}`),

  runCost: (runId: string) => getJSON<RunCostDetail>(`/runs/${runId}/cost`),
}
