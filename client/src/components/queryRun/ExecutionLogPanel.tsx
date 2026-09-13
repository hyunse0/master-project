import { useEffect, useRef, useState } from 'react'
import type { LogLine } from '../../types'

interface Props {
  logs: LogLine[]
  isRunning: boolean
  // 멀티턴에서 여러 턴의 로그를 한 패널에 이어붙여 보여줄 때 붙이는 라벨(예: "· 3 turns").
  countSuffix?: string
}

/** 그래프 노드가 실제로 찍는 로그(app.* 로거)를 run 단위로 모아 보여주는 패널.
 * POST /runs·resume이 동기 블로킹이라 줄 단위 실시간 스트리밍은 아니고, 요청이 끝날 때마다
 * 그 라운드에서 캡처된 로그가 한 번에 반영된다 — isRunning 동안은 "다음 라운드 로그 수신
 * 대기" 정도의 의미로만 tailing 표시를 보여준다. */
export function ExecutionLogPanel({ logs, isRunning, countSuffix }: Props) {
  const [openOverride, setOpenOverride] = useState<boolean | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const open = openOverride ?? true

  useEffect(() => {
    if (open && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [logs.length, open])

  const warnCount = logs.filter((l) => l.level !== 'info').length

  return (
    <section className="log-panel">
      <div
        className="log-panel-head"
        onClick={() => setOpenOverride(!open)}
        role="button"
        tabIndex={0}
      >
        <span className="log-chevron">{open ? '⌄' : '›'}</span>
        <span className="log-panel-title">실행 로그</span>
        <span className="log-count-label">{logs.length} lines{countSuffix ?? ''}</span>
        {warnCount > 0 && <span className="log-warn-badge">warn {warnCount}</span>}
        <div className="header-spacer" />
        <span className="log-tail-hint">
          {isRunning ? '요청 처리 중' : logs.length === 0 ? '대기 중' : '실행 종료'}
        </span>
      </div>

      {open && (
        <div className="log-panel-body" ref={bodyRef}>
          {logs.length === 0 && !isRunning && (
            <p className="log-empty-text">실행하면 여기에 로그가 표시됩니다.</p>
          )}
          {logs.map((l, i) => (
            <div className="log-line" key={i}>
              {l.turn != null && <span className="log-turn">T{l.turn}</span>}
              <span className="log-ts">{l.ts}</span>
              <span className={`log-level log-level-${l.level}`}>{l.level}</span>
              <span className={`log-msg log-msg-${l.level}`}>{l.msg}</span>
            </div>
          ))}
          {isRunning && (
            <div className="log-tailing">
              <span className="log-tailing-dot" />
              <span className="log-tailing-text">
                {logs.length === 0 ? '로그 수신 대기…' : '다음 구간 로그 수신 대기…'}
              </span>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
