export interface SchemaCandidateDetail {
  table: string
  comment: string | null
  score: number
  columns: string[]
}

export interface LogLine {
  ts: string
  level: 'info' | 'warn' | 'error'
  msg: string
}

export interface RunResult {
  run_id: string
  status: 'interrupted_schema' | 'interrupted_sql' | 'success' | 'error'
  domain: string
  question: string
  review_config: ReviewConfig
  difficulty: 'easy' | 'medium' | 'hard' | null
  query_type: 'aggregate' | 'list' | 'cohort' | null
  task_type: string | null
  schema_candidates: string[]
  schema_candidate_details: SchemaCandidateDetail[]
  confirmed_schema: string[]
  sql: string | null
  columns: string[]
  rows: Record<string, unknown>[]
  row_count: number | null
  summary: string | null
  execution_error: string | null
  retry_error_code: string | null
  retry_feedback: string | null
  retries: number
  max_retries: number
  latency_ms: number
  sql_edited: boolean
  // 사람이 SQL을 실제로 고쳤을 때만(sql_edited=true) 채워진다 — 아니면 둘 다 null.
  sql_before_edit: string | null
  correction_reason: string | null
  logs: LogLine[]
}

export interface ReviewConfig {
  schema: boolean
  sql: boolean
}

// runs 레지스트리의 status는 RunResult.status(4종) 외에 'running'(생성 직후, 아직 한 번도
// 끝나지 않은 상태)이 하나 더 있다 — POST /runs·resume이 동기 블로킹이라 정상적으로는 응답이
// 오기 전까지만 잠깐 걸치는 상태지만, 다른 세션이 같은 run을 돌리고 있거나 프로세스가 죽어
// _mark_crashed도 못 탄 경우엔 레지스트리에 그대로 남는다.
export type RunListStatus = RunResult['status'] | 'running'

export interface RunSummary {
  run_id: string
  domain: string
  question: string
  status: RunListStatus
  created_at: string
  retries: number
  row_count: number | null
  latency_ms: number | null
}

export interface RunListResponse {
  runs: RunSummary[]
  has_more: boolean
}

// GET /fewshot/candidates — 히스토리에서 사람이 SQL을 직접 고쳐 승인했지만 아직 few-shot으로
// 채택 안 한 run. sql_edited=true인 run에서만 나오므로 sql_before_edit/sql은 항상 둘 다 있다.
export interface FewShotCandidate {
  run_id: string
  domain: string
  question: string
  created_at: string
  sql_before_edit: string
  sql: string
  correction_reason: string | null
  confirmed_schema: string[]
  task_type: string | null
}

// GET /fewshot/entries — domains/<domain>/few_shot.json에 이미 채택된 항목.
// reflected는 저장할 때 고정되는 값이 아니라 조회 시점에 Qdrant와 대조해 매번 다시 계산된다.
export interface FewShotEntry {
  id: string
  question: string
  intent: string
  sql: string
  tables: string[]
  metrics: string[]
  domain: string
  source_run_id: string | null
  sql_before_edit: string | null
  correction_reason: string | null
  added_at: string | null
  reflected: boolean
}
