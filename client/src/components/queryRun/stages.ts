import type { RunResult } from '../../types'

export type StageStatus = 'idle' | 'done' | 'waiting' | 'running' | 'failed'

// POST /runs·resume은 동기 호출이라 한 번의 요청이 여러 노드를 한 번에 통과할 수 있다
// (예: review_config가 둘 다 꺼져 있으면 요청 1번이 intent~execution 전체를 커버).
// running_* 3가지는 "지금 어느 네트워크 요청이 떠 있는가"를 구분하는 기본 단위이자,
// 아래 NODE_TO_STAGE_NO 기반 실시간 위치(GET /runs/{id}/progress 폴링, useRunReview 참고)를
// 아직 못 받았을 때의 폴백이다 — SSE 스트리밍 없이도 진행 중인 실제 노드를 이 폴링으로
// 알아내므로, 스테이지 레일은 이제 지어낸 앵커가 아니라 실제 위치를 보여준다.
export type RunningPhase = 'running_create' | 'running_after_schema' | 'running_after_sql'
export type Phase = 'idle' | RunningPhase | 'schema_review' | 'sql_review' | 'done' | 'failed'

// running_* phase → 그 요청이 걸쳐 있는 동안 강조해서 보여줄 스테이지 번호(STAGE_DEFS의 no).
// GET /runs/{id}/progress 폴링으로 실제 실행 중인 노드를 알아내지 못했을 때(첫 폴링 응답이
// 오기 전, 혹은 폴링 자체가 실패했을 때)의 폴백 앵커 — 이 번호부터 다음 정지 지점까지 통째로
// 진행되는 구간의 시작점이다.
export const RUNNING_STAGE_NO: Record<RunningPhase, string> = {
  running_create: '1',
  running_after_schema: '3',
  running_after_sql: '4',
}

// 백엔드 그래프 노드 이름(app/graph/build.py에 등록된 이름과 동일) → 스테이지 레일 번호.
// GET /runs/{id}/progress가 돌려주는 current_node를 실제 스테이지 박스에 매핑하는 용도.
export const NODE_TO_STAGE_NO: Record<string, string> = {
  intent: '1',
  intent_clarification: '1',
  schema_linking: '2',
  schema_review: '2',
  sql_generation: '3',
  sql_review: '3',
  validation: '4',
  execution: '5',
}

export const NODE_LABEL: Record<string, string> = {
  intent: '의도 분류',
  intent_clarification: '의도 확인',
  schema_linking: '스키마 탐색',
  schema_review: '스키마 검토',
  sql_generation: 'SQL 생성',
  sql_review: 'SQL 검토',
  validation: '검증',
  execution: '실행',
}

export interface StageView {
  no: string
  label: string
  isGate: boolean
  gateKey: 'schema' | 'sql' | null
  status: StageStatus
  meta: string
}

interface ReviewCfg {
  schema: boolean
  sql: boolean
}

// 실제 파이프라인은 스키마 검토/SQL 검토가 별도 노드지만, 스테이지 레일에는 검토 대기를
// 별도 박스로 두지 않고 "스키마 탐색"/"SQL 생성" 박스 자체의 상태(waiting)로 합쳐서 보여준다 —
// 그 스테이지에 딸린 검토 게이트를 같은 박스의 체크박스로 켜고 끌 수 있게 하기 위함.
const STAGE_DEFS: { no: string; label: string; gate: 'schema' | 'sql' | null }[] = [
  { no: '1', label: '의도 분류', gate: null },
  { no: '2', label: '스키마 탐색', gate: 'schema' },
  { no: '3', label: 'SQL 생성', gate: 'sql' },
  { no: '4', label: '검증', gate: null },
  { no: '5', label: '실행', gate: null },
]

/** retry_error_code로부터 실패가 실제로 발생한 스테이지 인덱스(0-based)를 판정한다.
 * validation_node는 첫 실패에서 멈추므로 그 앞 스테이지들은 실제로 통과한 것이 맞다. */
export function failedStageIndex(code: string | null): number {
  if (code === 'VALUE_UNCONFIRMED') return 2 // SQL 생성 — 값 확정 실패
  if (code === 'JOIN_INVALID' || code === 'SCHEMA_CITATION_FAIL' || code === 'VALUE_ANCHOR_FAIL' || code === 'SQL_VALIDATION_FAIL') return 3 // 검증
  if (code === 'TIMEOUT' || code === 'UNSAFE_SQL' || code === 'ZERO_ROWS_WITH_VALUE_FILTER') return 4 // 실행
  return -1
}

export function isRunningPhase(phase: Phase): phase is RunningPhase {
  return phase in RUNNING_STAGE_NO
}

/** running_* phase에서 실제 앵커로 쓸 스테이지 번호 — GET /runs/{id}/progress 폴링으로 얻은
 * currentNode가 있으면 그걸 우선하고, 없으면(첫 응답 전/폴링 실패) RUNNING_STAGE_NO로 폴백. */
function runningStageNo(phase: Phase, currentNode?: string | null): string | null {
  if (!isRunningPhase(phase)) return null
  if (currentNode && NODE_TO_STAGE_NO[currentNode]) return NODE_TO_STAGE_NO[currentNode]
  return RUNNING_STAGE_NO[phase]
}

/** 현재 phase가 가리키는 스테이지 인덱스(0-based). 진행 중이든 검토 대기든 실패든,
 * "지금 화면에 보여줘야 할 스테이지"가 어디인지를 하나로 계산한다 — 스테이지 레일 색칠과
 * "각 스테이지 클릭 시 상세보기" 둘 다 이 값을 기준으로 삼는다. */
export function activeStageIndex(phase: Phase, result: RunResult | null, currentNode?: string | null): number {
  const runningNo = runningStageNo(phase, currentNode)
  if (runningNo) return Number(runningNo) - 1
  if (phase === 'schema_review') return 1
  if (phase === 'sql_review') return 2
  if (phase === 'done') return 5
  if (phase === 'failed') return failedStageIndex(result?.retry_error_code ?? null)
  return -1
}

export function computeStages(
  phase: Phase,
  cfg: ReviewCfg,
  result: RunResult | null,
  currentNode?: string | null,
): StageView[] {
  const runningNo = runningStageNo(phase, currentNode)
  const activeIdx = activeStageIndex(phase, result, currentNode)
  const failIdx = phase === 'failed' ? activeIdx : -1

  return STAGE_DEFS.map((def, i) => {
    const gateActive = def.gate === 'schema' ? cfg.schema : def.gate === 'sql' ? cfg.sql : false
    const waiting = (phase === 'schema_review' && def.no === '2') || (phase === 'sql_review' && def.no === '3')
    const running = runningNo === def.no
    const failed = phase === 'failed' && i === failIdx
    const done = !failed && !running && i < activeIdx

    let status: StageStatus = 'idle'
    if (waiting) status = 'waiting'
    else if (running) status = 'running'
    else if (failed) status = 'failed'
    else if (done) status = 'done'

    let meta: string
    if (waiting) meta = '검토 대기'
    else if (running) meta = '진행 중'
    else if (failed) meta = '실패'
    // done 상태로 여기 오는 게이트 스테이지는 검토가 켜져 있었을 때만 사람이 실제로 승인한 것 —
    // 꺼져 있었다면 검토 없이 자동으로 지나간 것이므로 원래 결과 메타를 그대로 보여준다.
    else if (done) meta = def.gate && gateActive ? '검토 승인됨' : stageMeta(def.no, result)
    else meta = '대기'

    return { no: def.no, label: def.label, isGate: def.gate !== null, gateKey: def.gate, status, meta }
  })
}

function stageMeta(no: string, result: RunResult | null): string {
  if (!result) return ''
  switch (no) {
    case '1': {
      const parts: string[] = []
      if (result.difficulty) parts.push(`난이도 ${result.difficulty}`)
      if (result.query_type) parts.push(`유형 ${result.query_type}`)
      return parts.join(' · ')
    }
    case '2':
      return `후보 ${result.schema_candidates.length}건`
    case '3': {
      const base = result.retries > 0 ? `재시도 ${result.retries}회` : '생성 완료'
      const model = result.node_models?.sql_generation
      return model ? `${base} · ${model}` : base
    }
    case '4':
      return '4개 체크 통과'
    case '5':
      return result.row_count != null ? `${result.row_count}행 · ${result.latency_ms}ms` : ''
    default:
      return ''
  }
}

export const RUNNING_STAGE_TITLE: Record<RunningPhase, string> = {
  running_create: '질의 처리 중',
  running_after_schema: 'SQL 생성 및 검증 중',
  running_after_sql: '검증 및 실행 중',
}

export const RUNNING_STAGE_SUB: Record<RunningPhase, string> = {
  running_create:
    '의도 분류부터 다음 정지 지점(검토 또는 완료)까지 한 번의 요청으로 처리합니다.',
  running_after_schema: '확정된 스키마로 SQL을 생성하고 다음 정지 지점까지 검증합니다.',
  running_after_sql: '승인된 SQL을 스키마 인용 / 값 존재 / 안전성 순서로 검증한 뒤 실행합니다.',
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

  const join: CheckItem = { name: '조인 정합성 검증', detail: '통과', ok: true }
  const citation: CheckItem = { name: '스키마 인용 검증', detail: '통과', ok: true }
  const anchor: CheckItem = { name: '값 존재 검증', detail: '통과', ok: true }
  const safety: CheckItem = { name: '안전성 검증', detail: '통과', ok: true }

  if (code === 'JOIN_INVALID') {
    join.ok = false
    join.detail = feedback
    citation.detail = '확인 전'
    anchor.detail = '확인 전'
    safety.detail = '확인 전'
    return [join, citation, anchor, safety]
  }
  if (code === 'SCHEMA_CITATION_FAIL') {
    citation.ok = false
    citation.detail = feedback
    anchor.detail = '확인 전'
    safety.detail = '확인 전'
    return [join, citation, anchor, safety]
  }
  if (code === 'VALUE_ANCHOR_FAIL') {
    anchor.ok = false
    anchor.detail = feedback
    safety.detail = '확인 전'
    return [join, citation, anchor, safety]
  }
  if (code === 'SQL_VALIDATION_FAIL') {
    safety.ok = false
    safety.detail = feedback
    return [join, citation, anchor, safety]
  }

  // TIMEOUT / UNSAFE_SQL / ZERO_ROWS_WITH_VALUE_FILTER — 검증은 전부 통과하고 실행 단계에서 실패
  const execution: CheckItem = { name: '실행', detail: feedback, ok: false }
  return [join, citation, anchor, safety, execution]
}
