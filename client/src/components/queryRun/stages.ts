import type { RunResult } from '../../types'

export type StageStatus = 'idle' | 'done' | 'waiting' | 'running' | 'failed' | 'skipped'
export type RunningPhase =
  | 'running_intent'
  | 'running_schema'
  | 'running_sql'
  | 'running_validate'
  | 'running_exec'
export type Phase = 'idle' | RunningPhase | 'schema_review' | 'sql_review' | 'done' | 'failed'

// running_* phase → 그 단계가 대응하는 스테이지 번호(STAGE_DEFS의 no)
export const RUNNING_STAGE_NO: Record<RunningPhase, string> = {
  running_intent: '1',
  running_schema: '2',
  running_sql: '4',
  running_validate: '6',
  running_exec: '7',
}

export interface StageView {
  no: string
  label: string
  isGate: boolean
  status: StageStatus
  meta: string
}

interface ReviewCfg {
  schema: boolean
  sql: boolean
}

const STAGE_DEFS: { no: string; label: string; gate: 'schema' | 'sql' | null }[] = [
  { no: '1', label: '의도 분류', gate: null },
  { no: '2', label: '스키마 탐색', gate: null },
  { no: '3', label: '스키마 검토', gate: 'schema' },
  { no: '4', label: 'SQL 생성', gate: null },
  { no: '5', label: 'SQL 검토', gate: 'sql' },
  { no: '6', label: '검증', gate: null },
  { no: '7', label: '실행', gate: null },
]

/** retry_error_code로부터 실패가 실제로 발생한 스테이지 인덱스(0-based)를 판정한다.
 * validation_node는 첫 실패에서 멈추므로 그 앞 스테이지들은 실제로 통과한 것이 맞다. */
export function failedStageIndex(code: string | null): number {
  if (code === 'VALUE_UNCONFIRMED') return 3 // SQL 생성 — 값 확정 실패
  if (code === 'SCHEMA_CITATION_FAIL' || code === 'VALUE_ANCHOR_FAIL' || code === 'SQL_VALIDATION_FAIL') return 5 // 검증
  if (code === 'TIMEOUT' || code === 'UNSAFE_SQL' || code === 'ZERO_ROWS_WITH_VALUE_FILTER') return 6 // 실행
  return -1
}

export function isRunningPhase(phase: Phase): phase is RunningPhase {
  return phase in RUNNING_STAGE_NO
}

/** 현재 phase가 가리키는 스테이지 인덱스(0-based). 진행 중이든 검토 대기든 실패든,
 * "지금 화면에 보여줘야 할 스테이지"가 어디인지를 하나로 계산한다 — 스테이지 레일 색칠과
 * "각 스테이지 클릭 시 상세보기" 둘 다 이 값을 기준으로 삼는다. */
export function activeStageIndex(phase: Phase, result: RunResult | null): number {
  const runningNo = isRunningPhase(phase) ? RUNNING_STAGE_NO[phase] : null
  if (runningNo) return Number(runningNo) - 1
  if (phase === 'schema_review') return 2
  if (phase === 'sql_review') return 4
  if (phase === 'done') return 7
  if (phase === 'failed') return failedStageIndex(result?.retry_error_code ?? null)
  return -1
}

export function computeStages(phase: Phase, cfg: ReviewCfg, result: RunResult | null): StageView[] {
  const runningNo = isRunningPhase(phase) ? RUNNING_STAGE_NO[phase] : null
  const activeIdx = activeStageIndex(phase, result)
  const failIdx = phase === 'failed' ? activeIdx : -1

  return STAGE_DEFS.map((def, i) => {
    const gateActive = def.gate === 'schema' ? cfg.schema : def.gate === 'sql' ? cfg.sql : true
    const skipped = def.gate !== null && !gateActive
    const waiting = (phase === 'schema_review' && def.no === '3') || (phase === 'sql_review' && def.no === '5')
    const running = runningNo === def.no
    const failed = phase === 'failed' && i === failIdx
    const done = !skipped && !failed && !running && i < activeIdx

    let status: StageStatus = 'idle'
    if (skipped) status = 'skipped'
    else if (waiting) status = 'waiting'
    else if (running) status = 'running'
    else if (failed) status = 'failed'
    else if (done) status = 'done'

    let meta: string
    if (skipped) meta = '건너뜀'
    else if (waiting) meta = '검토 대기'
    else if (running) meta = '진행 중'
    else if (failed) meta = '실패'
    else if (done) meta = stageMeta(def.no, result)
    else meta = '대기'

    return { no: def.no, label: def.label, isGate: def.gate !== null, status, meta }
  })
}

function stageMeta(no: string, result: RunResult | null): string {
  if (!result) return ''
  switch (no) {
    case '1':
      return result.difficulty ? `난이도 ${result.difficulty}` : ''
    case '2':
      return `후보 ${result.schema_candidates.length}건`
    case '3':
      return '자동승인'
    case '4':
      return result.retries > 0 ? `재시도 ${result.retries}회` : '생성 완료'
    case '5':
      return '자동승인'
    case '6':
      return '3개 체크 통과'
    case '7':
      return result.row_count != null ? `${result.row_count}행 · ${result.latency_ms}ms` : ''
    default:
      return ''
  }
}

export const RUNNING_STAGE_TITLE: Record<RunningPhase, string> = {
  running_intent: '의도 분류 중',
  running_schema: '스키마 탐색 중',
  running_sql: 'SQL 생성 중',
  running_validate: 'SQL 검증 중',
  running_exec: '쿼리 실행 중',
}

export const RUNNING_STAGE_SUB: Record<RunningPhase, string> = {
  running_intent: '질문의 난이도와 유형을 분류합니다.',
  running_schema: '질의와 유사한 테이블을 벡터 검색으로 찾습니다.',
  running_sql: '확정된 스키마만 인용해 SQL을 생성합니다.',
  running_validate: '스키마 인용 / 값 존재 / 안전성을 순서대로 확인합니다.',
  running_exec: '읽기 전용 커넥션으로 SQL을 실행합니다.',
}

export interface CheckItem {
  name: string
  detail: string
  ok: boolean
}

/** validation_node는 첫 실패에서 멈추므로, 실패 지점 이전 체크는 실제로 통과한 것이고
 * 이후 체크는 아예 실행되지 않은 것 — 셋 다 "통과"로 지어내지 않는다. */
export function buildChecks(result: RunResult): CheckItem[] {
  const code = result.retry_error_code
  const feedback = result.retry_feedback ?? result.execution_error ?? '오류 상세 정보 없음'

  if (code === 'VALUE_UNCONFIRMED') {
    return [{ name: 'SQL 생성 — 값 확정', detail: feedback, ok: false }]
  }

  const citation: CheckItem = { name: '스키마 인용 검증', detail: '통과', ok: true }
  const anchor: CheckItem = { name: '값 존재 검증', detail: '통과', ok: true }
  const safety: CheckItem = { name: '안전성 검증', detail: '통과', ok: true }

  if (code === 'SCHEMA_CITATION_FAIL') {
    citation.ok = false
    citation.detail = feedback
    anchor.detail = '확인 전'
    safety.detail = '확인 전'
    return [citation, anchor, safety]
  }
  if (code === 'VALUE_ANCHOR_FAIL') {
    anchor.ok = false
    anchor.detail = feedback
    safety.detail = '확인 전'
    return [citation, anchor, safety]
  }
  if (code === 'SQL_VALIDATION_FAIL') {
    safety.ok = false
    safety.detail = feedback
    return [citation, anchor, safety]
  }

  // TIMEOUT / UNSAFE_SQL / ZERO_ROWS_WITH_VALUE_FILTER — 검증은 전부 통과하고 실행 단계에서 실패
  const execution: CheckItem = { name: '실행', detail: feedback, ok: false }
  return [citation, anchor, safety, execution]
}
