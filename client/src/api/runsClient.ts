import type { ReviewConfig, RunResult } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function handle(res: Response): Promise<RunResult> {
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `요청 실패: ${res.status}`)
  }
  return res.json() as Promise<RunResult>
}

export const runsApi = {
  // POST /runs는 동기 호출 — 다음 interrupt(스키마/SQL 검토) 또는 그래프 종료까지 블로킹한다.
  create: (question: string, domain?: string, reviewConfig?: ReviewConfig): Promise<RunResult> =>
    fetch(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, domain, review_config: reviewConfig }),
    }).then(handle),

  // 새로고침/재접속 시 현재 run 상태를 다시 읽기 위한 것 — 진행 중 폴링용이 아니다
  // (POST /runs·resume 자체가 동기 호출이라 그 사이엔 조회할 "진행 중" 상태가 없다).
  get: (runId: string): Promise<RunResult> => fetch(`${API_BASE}/runs/${runId}`).then(handle),

  // status가 interrupted_schema면 confirmed_schema를, interrupted_sql이면 sql을 보낸다.
  resume: (runId: string, body: { confirmed_schema?: string[]; sql?: string }): Promise<RunResult> =>
    fetch(`${API_BASE}/runs/${runId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),
}
