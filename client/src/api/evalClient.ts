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

export interface GoldenSetLastRun {
  run_id: string
  ok: boolean
  generated_sql: string | null
  created_at: string
}

export interface GoldenSetCase {
  question: string
  expected_sql: string
  // F단계(멀티턴) — 대화 몇 번째의 몇 번째 턴인지. 화면은 아직 이 값을 쓰지 않는다.
  conversation_index: number
  turn_no: number
  last_run: GoldenSetLastRun | null
}

export interface GoldenSetList {
  domain: string | null
  cases: GoldenSetCase[]
}

export interface ExecutionAccuracyJob {
  status: 'running' | 'done' | 'error'
  done: number
  total: number
  last_question: string | null
  result: {
    skipped: boolean
    reason: string | null
    total: number
    correct: number
    accuracy: number | null
    schema_mapping: { precision: number; recall: number; f1: number } | null
    faithfulness: { total: number; faithful: number; ratio: number | null } | null
  } | null
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface ExecutionAccuracyJobStart {
  status: 'started' | 'already_running'
  job: ExecutionAccuracyJob
}

export interface ExecutionAccuracyJobStatus {
  job: ExecutionAccuracyJob | null
}

export interface SelfCorrectionJob {
  status: 'running' | 'done' | 'error'
  done: number
  total: number
  last_question: string | null
  last_outcome: string | null
  result: {
    skipped: boolean
    reason: string | null
    total: number
    outcomes: Record<string, number>
    corrected_by_first_error: Record<string, number>
    still_failed_by_first_error: Record<string, number>
  } | null
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface SelfCorrectionJobStart {
  status: 'started' | 'already_running'
  job: SelfCorrectionJob
}

export interface SelfCorrectionJobStatus {
  job: SelfCorrectionJob | null
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(`${path} 요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${path} 요청 실패: ${res.status}`)
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

  goldenSet: (domain?: string) => getJSON<GoldenSetList>(`/eval/golden-set${buildQuery({ domain })}`),

  runExecutionAccuracy: (domain: string) =>
    postJSON<ExecutionAccuracyJobStart>(`/eval/execution-accuracy/run${buildQuery({ domain })}`),

  executionAccuracyStatus: (domain: string) =>
    getJSON<ExecutionAccuracyJobStatus>(`/eval/execution-accuracy/run-status${buildQuery({ domain })}`),

  runSelfCorrection: (domain: string) =>
    postJSON<SelfCorrectionJobStart>(`/eval/self-correction/run${buildQuery({ domain })}`),

  selfCorrectionStatus: (domain: string) =>
    getJSON<SelfCorrectionJobStatus>(`/eval/self-correction/run-status${buildQuery({ domain })}`),
}
