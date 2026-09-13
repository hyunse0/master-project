const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface ModelConfigCurrent {
  chat_low: string | null
  chat_high: string | null
  chat_judge: string | null
  embedding: string | null
}

export interface ModelConfigResponse {
  options: { chat: string[]; embedding: string[] }
  current: ModelConfigCurrent
}

export type ModelConfigUpdate = Partial<ModelConfigCurrent>

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`요청 실패: ${res.status}`)
  return res.json() as Promise<T>
}

export const modelConfigApi = {
  get: () => fetch(`${API_BASE}/model-config`).then((r) => json<ModelConfigResponse>(r)),

  update: (body: ModelConfigUpdate) =>
    fetch(`${API_BASE}/model-config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => json<ModelConfigResponse>(r)),
}
