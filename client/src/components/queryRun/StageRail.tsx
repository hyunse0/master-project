import type { StageView } from './stages'

const DOT_MARK: Record<StageView['status'], string> = {
  idle: '',
  done: '✓',
  waiting: '!',
  running: '·',
  failed: '×',
  skipped: '',
}

interface Props {
  stages: StageView[]
  selectedNo?: string | null
  onSelect?: (no: string) => void
}

export function StageRail({ stages, selectedNo, onSelect }: Props) {
  return (
    <div className="stage-rail">
      {stages.map((s, i) => {
        const clickable = !!onSelect && s.status !== 'idle'
        return (
          <div className="stage-cell" key={s.no}>
            <div
              className={`stage-box status-${s.status} ${s.no === selectedNo ? 'selected' : ''} ${clickable ? 'clickable' : ''}`}
              onClick={clickable ? () => onSelect!(s.no) : undefined}
              role={clickable ? 'button' : undefined}
              tabIndex={clickable ? 0 : undefined}
            >
              <div className="stage-box-top">
                <span className={`stage-dot status-${s.status}`}>{DOT_MARK[s.status]}</span>
                <span className="stage-no">{s.no}</span>
                {s.isGate && <span className="stage-hitl-badge">HITL</span>}
              </div>
              <span className="stage-label">{s.label}</span>
              <span className="stage-meta">{s.meta}</span>
            </div>
            {i < stages.length - 1 && <span className="stage-arrow">›</span>}
          </div>
        )
      })}
    </div>
  )
}
