import type { ReviewConfig } from '../../types'
import type { StageView } from './stages'

const DOT_MARK: Record<StageView['status'], string> = {
  idle: '',
  done: '✓',
  waiting: '!',
  running: '·',
  failed: '×',
}

interface Props {
  stages: StageView[]
  cfg: ReviewConfig
  onToggleGate: (key: 'schema' | 'sql') => void
  selectedNo?: string | null
  onSelect?: (no: string) => void
  // 과거 run을 다시 보여줄 때 — 이미 끝난 run의 검토 설정은 되돌려 바꿀 수 없으므로 토글을 잠근다.
  readOnly?: boolean
}

export function StageRail({ stages, cfg, onToggleGate, selectedNo, onSelect, readOnly }: Props) {
  return (
    <div className="stage-rail">
      {stages.map((s, i) => {
        const clickable = !!onSelect && s.status !== 'idle'
        const gateOn = s.gateKey ? cfg[s.gateKey] : false
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
                {s.isGate && s.gateKey && (
                  <label className="stage-gate-toggle" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={gateOn}
                      disabled={readOnly}
                      onChange={() => onToggleGate(s.gateKey!)}
                    />
                    <span className={gateOn ? 'on' : ''}>검토</span>
                  </label>
                )}
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
