import type { RunResult } from '../../types'

interface Props {
  result: RunResult
}

/** 검증 3항목(스키마 인용/값 존재/안전성)의 통과 여부를 보여준다.
 * validation_node는 첫 실패에서 멈추므로, 검증 단계에서 실제로 멈춘 게 아니면(성공,
 * 또는 이후 실행 단계에서 실패) 셋 다 통과가 맞다 — 지어내는 게 아니라 실제로 그렇다. */
export function ValidateChecklist({ result }: Props) {
  const failedHere = result.retry_error_code
    ? ['JOIN_INVALID', 'SCHEMA_CITATION_FAIL', 'VALUE_ANCHOR_FAIL', 'SQL_VALIDATION_FAIL'].includes(result.retry_error_code)
    : false

  const items = [
    { name: '조인 정합성 검증', code: 'JOIN_INVALID' },
    { name: '스키마 인용 검증', code: 'SCHEMA_CITATION_FAIL' },
    { name: '값 존재 검증', code: 'VALUE_ANCHOR_FAIL' },
    { name: '안전성 검증', code: 'SQL_VALIDATION_FAIL' },
  ].map((c) => {
    if (!failedHere || result.retry_error_code !== c.code) {
      return { name: c.name, detail: '통과', status: 'ok' as const }
    }
    return { name: c.name, detail: result.retry_feedback ?? '실패', status: 'fail' as const }
  })

  return (
    <div className="running-block">
      {items.map((k) => (
        <div key={k.name} className={`running-check-row status-${k.status}`}>
          <span className="running-check-mark">{k.status === 'ok' ? '✓' : '×'}</span>
          <span className="running-check-text">
            <span className="running-check-name">{k.name}</span>
            <span className="running-check-detail">{k.detail}</span>
          </span>
        </div>
      ))}
    </div>
  )
}
