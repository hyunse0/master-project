import { formatRelativeTime } from '../history/relativeTime'
import { STATUS_META, type FewShotItem } from './fewShotItem'

interface Props {
  item: FewShotItem
  onOpenRun: (runId: string) => void
  onAdd: (runId: string) => void
  onDelete: (entryId: string) => void
}

export function FewShotCard({ item, onOpenRun, onAdd, onDelete }: Props) {
  const meta = STATUS_META[item.status]
  const hasDiff = !!item.sqlBefore && item.sqlBefore.trim() !== item.sqlFinal.trim()

  return (
    <section className={`fewshot-card ${item.status === 'candidate' ? 'is-candidate' : ''}`}>
      <div className="fewshot-card-head">
        <span className={`fewshot-dot ${meta.badgeClass}`} />
        <div className="fewshot-card-head-main">
          <div className="fewshot-card-head-row">
            <span className={`run-status-badge ${meta.badgeClass}`}>{meta.label}</span>
            <span className="history-row-domain">{item.domain}</span>
            {item.at && (
              <>
                <span className="history-row-dot">·</span>
                <span className="review-section-hint">{formatRelativeTime(item.at)}</span>
              </>
            )}
            {item.runId && (
              <>
                <span className="history-row-dot">·</span>
                <button className="fewshot-run-link" onClick={() => onOpenRun(item.runId!)}>
                  {item.runId.slice(0, 8)}
                </button>
              </>
            )}
          </div>
          <p className="fewshot-question">{item.question}</p>
        </div>

        {item.status === 'candidate' && item.runId && (
          <button className="btn-primary" onClick={() => onAdd(item.runId!)}>
            few-shot에 추가
          </button>
        )}
        {item.status !== 'candidate' && item.entryId && (
          <button className="btn-danger-outline" onClick={() => onDelete(item.entryId!)}>
            삭제
          </button>
        )}
      </div>

      <div className="fewshot-card-body">
        <div className="result-block">
          <span className="review-section-label">수정 이유</span>
          <p className="fewshot-reason">{item.reason ?? '(입력 안 됨)'}</p>
        </div>

        {hasDiff ? (
          <div className="fewshot-diff">
            <div className="fewshot-diff-col">
              <div className="sql-review-label-row">
                <span className="review-section-label">AI 원본 SQL</span>
                <span className="review-section-hint">폐기됨</span>
              </div>
              <pre className="fewshot-sql-before">{item.sqlBefore}</pre>
            </div>
            <div className="fewshot-diff-col">
              <div className="sql-review-label-row">
                <span className="review-section-label" style={{ color: 'var(--review-text)' }}>
                  사람이 고친 최종 SQL
                </span>
                <span className="review-section-hint" style={{ color: 'var(--accent)' }}>
                  예제로 사용
                </span>
              </div>
              <pre className="sql-view-box">{item.sqlFinal}</pre>
            </div>
          </div>
        ) : (
          <div className="result-block">
            <div className="sql-review-label-row">
              <span className="review-section-label">최종 SQL</span>
              <span className="review-section-hint">AI 원본과 동일</span>
            </div>
            <pre className="sql-view-box">{item.sqlFinal}</pre>
          </div>
        )}

        {item.tables.length > 0 && (
          <div className="fewshot-tables-row">
            <span className="review-section-label">참조 테이블</span>
            {item.tables.map((t) => (
              <span key={t} className="fewshot-table-chip">{t}</span>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
