import type { FewShotCandidate, FewShotEntry } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const fewshotApi = {
  candidates: (domain: string): Promise<FewShotCandidate[]> =>
    fetch(`${API_BASE}/fewshot/candidates?domain=${encodeURIComponent(domain)}`).then(handle<FewShotCandidate[]>),

  entries: (domain: string): Promise<FewShotEntry[]> =>
    fetch(`${API_BASE}/fewshot/entries?domain=${encodeURIComponent(domain)}`).then(handle<FewShotEntry[]>),

  // 후보 하나를 few_shot.json에 채택한다 — 채택 즉시 Qdrant에 반영되는 건 아니다(POST /seed 별도).
  // 같은 run_id로 이미 채택돼 있으면 서버가 중복 생성 대신 기존 항목을 status: 'exists'로
  // 돌려준다(질의 실행 탭 결과 카드에서 같은 run을 여러 번 눌러도 안전하게).
  add: (domain: string, runId: string): Promise<FewShotEntry & { status: 'added' | 'exists' }> =>
    fetch(`${API_BASE}/fewshot/entries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain, run_id: runId }),
    }).then(handle<FewShotEntry & { status: 'added' | 'exists' }>),

  remove: (domain: string, entryId: string): Promise<{ deleted: string }> =>
    fetch(`${API_BASE}/fewshot/entries/${entryId}?domain=${encodeURIComponent(domain)}`, {
      method: 'DELETE',
    }).then(handle<{ deleted: string }>),

  // 지금 few_shot.json 전체 내용으로 Qdrant 컬렉션을 통째로 재구성한다(반영 버튼).
  seed: (domain: string): Promise<{ domain: string; count: number }> =>
    fetch(`${API_BASE}/fewshot/seed?domain=${encodeURIComponent(domain)}`, {
      method: 'POST',
    }).then(handle<{ domain: string; count: number }>),
}
