import type { SchemaCandidateDetail } from '../../types'

interface Props {
  candidates: SchemaCandidateDetail[]
  checked: Record<string, boolean>
  onToggle: (table: string) => void
  columnChecked: Record<string, Record<string, boolean>>
  onToggleColumn: (table: string, column: string) => void
  onCancel: () => void
  onApprove: () => void
}

export function SchemaReviewCard({
  candidates, checked, onToggle, columnChecked, onToggleColumn, onCancel, onApprove,
}: Props) {
  const selectedCount = candidates.filter((c) => checked[c.table]).length

  return (
    <section className="review-card">
      <div className="review-card-head">
        <span className="review-pulse-dot" />
        <h2 className="review-card-title">스키마 검토 대기 — 3단계</h2>
        <p className="review-card-desc">
          질의에 사용할 테이블과 컬럼을 확정하세요. 핵심(PK/FK) 컬럼은 조인에 필요해 항상
          포함되고, 기타 컬럼은 이름만 펼쳐볼 수 있습니다.
        </p>
      </div>

      <div className="review-card-body">
        <div className="schema-candidate-grid">
          {candidates.map((c) => {
            const isChecked = !!checked[c.table]
            const tiers = c.column_tiers
            const colChecks = columnChecked[c.table] ?? {}
            return (
              <div key={c.table} className={`schema-candidate-card ${isChecked ? 'checked' : ''}`}>
                <label className="schema-candidate-head-row">
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

                {isChecked && (
                  <div className="schema-col-panel">
                    {tiers.key.length > 0 && (
                      <div className="schema-col-group">
                        {tiers.key.map((name) => (
                          <span key={name} className="schema-col-row schema-col-locked">
                            <input type="checkbox" checked disabled />
                            <span className="schema-col-name">{name}</span>
                            <span className="schema-col-badge">KEY</span>
                          </span>
                        ))}
                      </div>
                    )}
                    {tiers.relevant.length > 0 && (
                      <div className="schema-col-group">
                        {tiers.relevant.map((name) => (
                          <label key={name} className="schema-col-row">
                            <input
                              type="checkbox"
                              checked={!!colChecks[name]}
                              onChange={() => onToggleColumn(c.table, name)}
                            />
                            <span className="schema-col-name">{name}</span>
                          </label>
                        ))}
                      </div>
                    )}
                    {tiers.other.length > 0 && (
                      <details className="schema-col-other-disclosure">
                        <summary>기타 컬럼 {tiers.other.length}개 보기</summary>
                        <div className="schema-col-group">
                          {tiers.other.map((name) => (
                            <label key={name} className="schema-col-row">
                              <input
                                type="checkbox"
                                checked={!!colChecks[name]}
                                onChange={() => onToggleColumn(c.table, name)}
                              />
                              <span className="schema-col-name">{name}</span>
                            </label>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
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
