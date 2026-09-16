import type { LogLine, ReviewConfig, RunListResponse, RunResult } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export interface RunListParams {
  domain?: string
  status?: string
  q?: string
  limit?: number
  before?: string
}

export const runsApi = {
  // POST /runs는 동기 호출 — 다음 interrupt(스키마/SQL 검토) 또는 그래프 종료까지 블로킹한다.
  // conversationId를 넘기면 그 대화의 다음 턴으로 이어지고(서버가 직전 턴 컨텍스트를 프롬프트에
  // 주입한다), 생략하면 새 대화의 1턴째로 시작한다. carrySchema는 turn_no>1일 때만 의미가
  // 있고, true면 schema_linking이 새로 검색하지 않고 직전 턴의 확정 스키마를 그대로 재사용한다.
  // runId를 넘기면 서버가 새로 발급하지 않고 그대로 쓴다 — 응답이 오기 전부터 progress()를
  // 폴링하려면 호출 전에 이미 run_id를 알고 있어야 하기 때문(useRunReview 참고).
  create: (
    question: string,
    domain?: string,
    reviewConfig?: ReviewConfig,
    conversationId?: string,
    carrySchema?: boolean,
    runId?: string,
  ): Promise<RunResult> =>
    fetch(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        domain,
        review_config: reviewConfig,
        conversation_id: conversationId,
        carry_schema: carrySchema,
        run_id: runId,
      }),
    }).then(handle<RunResult>),

  // 새로고침/재접속 시 현재 run 상태를 다시 읽기 위한 것.
  get: (runId: string): Promise<RunResult> => fetch(`${API_BASE}/runs/${runId}`).then(handle<RunResult>),

  // POST /runs·resume이 떠 있는 동안(동기 블로킹) 지금 어느 노드가 도는지, 지금까지 어떤
  // 로그가 찍혔는지 보려고 별도로 폴링하는 용도 — 메인 요청의 응답 계약과는 무관한 보조 조회.
  progress: (runId: string): Promise<{ current_node: string | null; logs: LogLine[] }> =>
    fetch(`${API_BASE}/runs/${runId}/progress`).then(handle<{ current_node: string | null; logs: LogLine[] }>),

  // status가 interrupted_schema면 confirmed_schema를, interrupted_sql이면 sql을 보낸다.
  // correction_reason은 SQL을 실제로 고쳤을 때만 의미가 있다(그렇지 않으면 서버가 무시한다).
  resume: (
    runId: string,
    body: {
      confirmed_schema?: string[]
      confirmed_columns?: Record<string, string[]>
      sql?: string
      correction_reason?: string
    },
  ): Promise<RunResult> =>
    fetch(`${API_BASE}/runs/${runId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle<RunResult>),

  // 실행 히스토리 탭의 목록 조회.
  list: (params: RunListParams = {}): Promise<RunListResponse> => {
    const usp = new URLSearchParams()
    if (params.domain) usp.set('domain', params.domain)
    if (params.status) usp.set('status', params.status)
    if (params.q) usp.set('q', params.q)
    if (params.limit) usp.set('limit', String(params.limit))
    if (params.before) usp.set('before', params.before)
    const qs = usp.toString()
    return fetch(`${API_BASE}/runs${qs ? `?${qs}` : ''}`).then(handle<RunListResponse>)
  },
}
