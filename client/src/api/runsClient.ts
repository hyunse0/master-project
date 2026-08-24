import type { RunResult } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export const runsApi = {
  // 지금은 자동 모드 전용 동기 엔드포인트 — review_config는 서버가 아직 무시한다.
  // C(interrupt/resume)가 구현되면 POST가 run_id만 반환하고 GET/{id}·POST/{id}/resume로 바뀐다.
  create: async (question: string, domain?: string): Promise<RunResult> => {
    const res = await fetch(`${API_BASE}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, domain }),
    })
    if (!res.ok) {
      const detail = await res.json().catch(() => null)
      throw new Error(detail?.detail ?? `실행 요청 실패: ${res.status}`)
    }
    return res.json() as Promise<RunResult>
  },
}
