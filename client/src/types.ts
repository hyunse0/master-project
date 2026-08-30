export interface SchemaCandidateDetail {
  table: string
  comment: string | null
  score: number
  columns: string[]
}

export interface RunResult {
  run_id: string
  status: 'interrupted_schema' | 'interrupted_sql' | 'success' | 'error'
  domain: string
  question: string
  review_config: ReviewConfig
  difficulty: 'easy' | 'medium' | 'hard' | null
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
}

export interface ReviewConfig {
  schema: boolean
  sql: boolean
}
