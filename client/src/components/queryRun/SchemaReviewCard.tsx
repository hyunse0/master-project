import type { SchemaCandidateDetail } from '../../types'

interface Props {
  candidates: SchemaCandidateDetail[]
  checked: Record<string, boolean>
  onToggle: (table: string) => void
  onCancel: () => void
  onApprove: () => void
}

export function SchemaReviewCard({ candidates, checked, onToggle, onCancel, onApprove }: Props) {
  const selectedCount = candidates.filter((c) => checked[c.table]).length

  return (
    <section className="review-card">
      <div className="review-card-head">
        <span className="review-pulse-dot" />
        <h2 className="review-card-title">스키마 검토 대기 — 3단계</h2>
        <p className="review-card-desc">질의에 사용할 테이블을 확정하세요. 체크를 해제하면 후보에서 제외됩니다.</p>
      </div>

      <div className="review-card-body">
        <div className="schema-candidate-grid">
          {candidates.map((c) => {
            const isChecked = !!checked[c.table]
            const tiers = c.column_tiers
            return (
              <label key={c.table} className={`schema-candidate-card ${isChecked ? 'checked' : ''}`}>
                <input type="checkbox" checked={isChecked} onChange={() => onToggle(c.table)} />
                <span className="schema-candidate-body">
                  <span className="schema-candidate-top">
                    <span className="schema-candidate-name">{c.table}</span>
                    <span className="schema-candidate-score">{Math.round(c.score * 100)}%</span>
                  </span>
                  <span className="schema-candidate-comment">{c.comment ?? '코멘트 없음'}</span>
                  <span className="schema-candidate-cols">
                    핵심 {tiers.key.length} · 관련 {tiers.relevant.length} · 기타 {tiers.other.length}
                  </span>
                </span>
              </label>
            )
          })}
        </div>

        <div className="review-card-actions">
          <span className="review-selected-label">
            {selectedCount} / {candidates.length}개 테이블 선택
          </span>
          <div className="review-card-spacer" />
          <button className="btn-secondary" onClick={onCancel}>
            실행 취소
          </button>
          <button className="btn-primary" onClick={onApprove}>
            confirmed_schema 승인
          </button>
        </div>
      </div>
    </section>
  )
}
