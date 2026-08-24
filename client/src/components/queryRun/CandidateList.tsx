import type { SchemaCandidateDetail } from '../../types'

interface Props {
  candidates: SchemaCandidateDetail[]
  /** true면 진행 중(running_schema) 연출용 페이드인 스태거 + "추가 후보 검색 중…" 문구를 붙인다. */
  live?: boolean
}

export function CandidateList({ candidates, live = false }: Props) {
  return (
    <>
      {candidates.map((c, i) => (
        <div
          className="running-candidate-row"
          key={c.table}
          style={live ? { animationDelay: `${i * 120}ms` } : undefined}
        >
          <div className="running-candidate-top">
            <span className="running-candidate-name">{c.table}</span>
            <span className="running-candidate-score">{Math.round(c.score * 100)}%</span>
          </div>
          <div className="running-bar-track">
            <div className="running-bar-fill" style={{ width: `${Math.round(c.score * 100)}%` }} />
          </div>
          <span className="running-candidate-comment">{c.comment ?? '코멘트 없음'}</span>
        </div>
      ))}
      {live && <span className="running-inline-text">추가 후보 검색 중…</span>}
    </>
  )
}
