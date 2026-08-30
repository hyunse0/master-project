import type { RunListStatus } from '../../types'

export const STATUS_LABEL: Record<RunListStatus, string> = {
  running: '실행중',
  interrupted_schema: '검토 대기(스키마)',
  interrupted_sql: '검토 대기(SQL)',
  success: '성공',
  error: '실패',
}

// App.css의 .run-status-badge.status-* 팔레트(질의 실행 탭에서 이미 쓰는 것)에 그대로 맞춘다 —
// running/interrupted_*는 검토대기와 같은 보라, success는 초록, error는 빨강.
export const STATUS_CLASS: Record<RunListStatus, string> = {
  running: 'status-running',
  interrupted_schema: 'status-interrupted_schema',
  interrupted_sql: 'status-interrupted_sql',
  success: 'status-success',
  error: 'status-error',
}

export const STATUS_OPTIONS: { value: RunListStatus; label: string }[] = [
  { value: 'running', label: STATUS_LABEL.running },
  { value: 'interrupted_schema', label: STATUS_LABEL.interrupted_schema },
  { value: 'interrupted_sql', label: STATUS_LABEL.interrupted_sql },
  { value: 'success', label: STATUS_LABEL.success },
  { value: 'error', label: STATUS_LABEL.error },
]
