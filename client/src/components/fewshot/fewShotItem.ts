import type { FewShotCandidate, FewShotEntry } from '../../types'

export type FewShotStatus = 'candidate' | 'saved' | 'synced'

export interface FewShotItem {
  key: string
  entryId: string | null // 저장됨/반영됨일 때만 있음 — 삭제 API가 이 id를 쓴다
  runId: string | null
  domain: string
  at: string | null
  status: FewShotStatus
  question: string
  reason: string | null
  sqlBefore: string | null
  sqlFinal: string
  tables: string[]
}

export function fromCandidate(c: FewShotCandidate): FewShotItem {
  return {
    key: `candidate:${c.run_id}`,
    entryId: null,
    runId: c.run_id,
    domain: c.domain,
    at: c.created_at,
    status: 'candidate',
    question: c.question,
    reason: c.correction_reason,
    sqlBefore: c.sql_before_edit,
    sqlFinal: c.sql,
    tables: c.confirmed_schema,
  }
}

export function fromEntry(e: FewShotEntry): FewShotItem {
  return {
    key: `entry:${e.id}`,
    entryId: e.id,
    runId: e.source_run_id,
    domain: e.domain,
    at: e.added_at,
    status: e.reflected ? 'synced' : 'saved',
    question: e.question,
    reason: e.correction_reason,
    sqlBefore: e.sql_before_edit,
    sqlFinal: e.sql,
    tables: e.tables,
  }
}

export const STATUS_META: Record<FewShotStatus, { label: string; badgeClass: string }> = {
  candidate: { label: '후보', badgeClass: 'status-candidate' },
  saved: { label: '저장됨 (미반영)', badgeClass: 'status-saved' },
  synced: { label: '반영됨', badgeClass: 'status-synced' },
}
