import type { RunResult } from '../../types'
import { buildChecks, failedStageIndex } from './stages'

const STAGE_NAME: Record<number, string> = {
  3: '4단계 SQL 생성',
  5: '6단계 검증',
  6: '7단계 실행',
}

interface Props {
  result: RunResult
  onRestart: () => void
}

export function FailedCard({ result, onRestart }: Props) {
  const checks = buildChecks(result)
  const stageIdx = failedStageIndex(result.retry_error_code)
  const stageName = STAGE_NAME[stageIdx] ?? '실행'

  return (
    <section className="failed-card">
      <div className="failed-card-head">
        <span className="failed-dot" />
        <h2 className="failed-card-title">실행 실패 — {stageName}</h2>
        <div className="review-card-spacer" />
        <span className="failed-retry-label">
          재시도 {result.retries}/{result.max_retries} 소진
        </span>
      </div>

      <div className="failed-card-body">
        <div className="failed-checks">
          {checks.map((k) => (
            <div key={k.name} className={`failed-check-row ${k.ok ? 'ok' : 'fail'}`}>
              <span className="failed-check-mark">{k.ok ? '✓' : '×'}</span>
              <span className="failed-check-text">
                <span className="failed-check-name">{k.name}</span>
                <span className="failed-check-detail">{k.detail}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="failed-card-actions">
          <button className="btn-danger-outline" onClick={onRestart}>
            처음부터 다시 실행
          </button>
        </div>
      </div>
    </section>
  )
}
