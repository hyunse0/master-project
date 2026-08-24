interface Props {
  sql: string
  onChange: (sql: string) => void
  retries: number
  runId: string
  refTables: string[]
  onApprove: () => void
}

export function SqlReviewCard({ sql, onChange, retries, runId, refTables, onApprove }: Props) {
  const lineCount = sql.split('\n').length

  return (
    <section className="review-card">
      <div className="review-card-head">
        <span className="review-pulse-dot" />
        <h2 className="review-card-title">SQL 검토 대기 — 5단계</h2>
        <p className="review-card-desc">수정한 SQL은 그대로 검증 단계로 전달되며 재생성으로 덮이지 않습니다.</p>
        <div className="review-card-spacer" />
        <span className="review-endpoint-label">POST /runs/{runId}/resume</span>
      </div>

      <div className="review-card-body">
        {retries > 0 && (
          <div className="review-retry-box">
            <span className="review-retry-box-title">생성 과정 참고</span>
            <span className="review-retry-box-detail">
              자동 검증 루프에서 {retries}회 재시도 후 확정된 SQL입니다.
            </span>
          </div>
        )}

        <div className="sql-review-label-row">
          <span className="review-section-label">GENERATED SQL</span>
          <span className="review-section-hint">편집 가능</span>
          <div className="review-card-spacer" />
          <span className="review-section-hint">{lineCount} lines</span>
        </div>

        <textarea
          className="sql-editor"
          value={sql}
          onChange={(e) => onChange(e.target.value)}
          rows={13}
          spellCheck={false}
        />

        <p className="review-preview-note">
          여기서 수정해도 실제 재검증에는 반영되지 않습니다 — 아래 승인 시 원래 실행 결과가 표시됩니다
          (재검증 연동은 C 단계에서 구현됩니다).
        </p>

        <div className="review-card-actions">
          <span className="review-selected-label">참조 테이블 {refTables.join(', ') || '없음'}</span>
          <div className="review-card-spacer" />
          <button className="btn-secondary" disabled title="구현 예정">
            재생성 요청
          </button>
          <button className="btn-primary" onClick={onApprove}>
            이 SQL로 검증 진행
          </button>
        </div>
      </div>
    </section>
  )
}
