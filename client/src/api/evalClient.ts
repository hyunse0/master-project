const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface AccuracyGroup {
  difficulty: string | null
  total: number
  correct: number
  accuracy: number
}

export interface ExecutionAccuracy {
  domain: string | null
  groups: AccuracyGroup[]
  overall: { total: number; correct: number; accuracy: number | null; last_run_at: string | null }
}

export interface SchemaMappingOverall {
  total: number
  precision: number | null
  recall: number | null
  f1: number | null
}

export interface SchemaMappingAccuracy {
  domain: string | null
  overall: SchemaMappingOverall | null
  groups: (SchemaMappingOverall & { difficulty: string | null })[]
}

export interface FaithfulnessFailure {
  run_id: string
  question: string
  reason: string | null
  summary: string | null
  columns: string[] | null
  rows: Record<string, unknown>[] | null
  created_at: string
}

export interface FaithfulnessSummary {
  domain: string | null
  overall: { total: number; faithful: number; ratio: number | null }
  failures: FaithfulnessFailure[]
}

export interface SelfCorrectionOutcome {
  outcome: string | null
  count: number
}

export interface SelfCorrectionByErrorCode {
  first_error_code: string | null
  outcome: string | null
  count: number
}

export interface SelfCorrectionSummary {
  domain: string | null
  outcomes: SelfCorrectionOutcome[]
  by_error_code: SelfCorrectionByErrorCode[]
}

export interface TokenCostGroup {
  tag_value: string | null
  total_tokens: number
  calls: number
  avg_latency_ms: number
  success_rate: number | null
  runs: number
}

export interface TokenCostComparison {
  domain: string | null
  experiment: string
  compare_key: string
  groups: TokenCostGroup[]
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

export const evalApi = {
  executionAccuracy: (domain?: string) =>
    getJSON<ExecutionAccuracy>(`/eval/execution-accuracy${buildQuery({ domain })}`),

  schemaMappingAccuracy: (domain?: string) =>
    getJSON<SchemaMappingAccuracy>(`/eval/schema-mapping-accuracy${buildQuery({ domain })}`),

  faithfulness: (domain?: string) =>
    getJSON<FaithfulnessSummary>(`/eval/faithfulness${buildQuery({ domain })}`),

  selfCorrection: (domain?: string) =>
    getJSON<SelfCorrectionSummary>(`/eval/self-correction${buildQuery({ domain })}`),

  tokenCost: (params: { domain?: string; experiment: string; compare_key: string }) =>
    getJSON<TokenCostComparison>(`/eval/token-cost${buildQuery(params)}`),
}
