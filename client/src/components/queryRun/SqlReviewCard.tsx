interface Props {
  sql: string
  onChange: (sql: string) => void
  retries: number
  runId: string
  refTables: string[]
  retryErrorCode: string | null
  retryFeedback: string | null
  edited: boolean
  correctionReason: string
  onCorrectionReasonChange: (reason: string) => void
  onApprove: () => void
}

export function SqlReviewCard({
  sql,
  onChange,
  retries,
  runId,
  refTables,
  retryErrorCode,
  retryFeedback,
  edited,
  correctionReason,
  onCorrectionReasonChange,
  onApprove,
}: Props) {
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
        {retryErrorCode && (
          <div className="review-retry-box danger">
            <span className="review-retry-box-title">이전 승인이 검증/실행에 실패해 되돌아왔습니다 ({retryErrorCode})</span>
            <span className="review-retry-box-detail">{retryFeedback ?? '상세 정보 없음'}</span>
          </div>
        )}

        {!retryErrorCode && retries > 0 && (
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

        {edited && (
          <div className="correction-reason-block">
            <span className="review-section-hint">
              수정 이유(선택) — 나중에 비슷한 질문에 참고 사례로 쓰일 수 있어요
            </span>
            <input
              className="correction-reason-input"
              value={correctionReason}
              onChange={(e) => onCorrectionReasonChange(e.target.value)}
              placeholder="예: 암종 정보는 patient가 아니라 cancer_registry 기준으로 조회해야 함"
            />
          </div>
        )}

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
