import type { SchemaCandidateDetail } from '../../types'

interface Props {
  candidates: SchemaCandidateDetail[]
}

export function CandidateList({ candidates }: Props) {
  return (
    <>
      {candidates.map((c) => (
        <div className="running-candidate-row" key={c.table}>
          <div className="running-candidate-top">
            <span className="running-candidate-name">{c.table}</span>
            <span className="running-candidate-score">{Math.round(c.score * 100)}%</span>
          </div>
          <div className="running-bar-track">
            <div className="running-bar-fill" style={{ width: `${Math.round(c.score * 100)}%` }} />
          </div>
          <span className="running-candidate-comment">{c.comment ?? '코멘트 없음'}</span>
          <span className="running-candidate-cols">
            핵심 {c.column_tiers.key.length} · 관련 {c.column_tiers.relevant.length} · 기타{' '}
            {c.column_tiers.other.length}
          </span>
        </div>
      ))}
    </>
  )
}
