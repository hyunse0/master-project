import type { ReviewConfig, RunResult } from '../../types'
import { CandidateList } from './CandidateList'
import { ValidateChecklist } from './ValidateChecklist'

interface Props {
  stageNo: string
  reachedIdx: number // 실제로 도달한 마지막 스테이지 인덱스(0-based) — 이후 단계는 미실행
  result: RunResult
  question: string
  cfg: ReviewConfig
}

const TITLE: Record<string, string> = {
  '1': '1단계 · 의도 분류 결과',
  '2': '2단계 · 스키마 탐색 및 검토',
  '3': '3단계 · SQL 생성 및 검토',
  '4': '4단계 · 검증 결과',
  '5': '5단계 · 실행 결과',
}

/** 실시간 진행 중이 아닌, 이미 지나간 스테이지를 클릭했을 때 보여주는 읽기 전용 스냅샷.
 * 새 데이터를 만들어내지 않고 result에 실제로 남아있는 값만 보여준다. */
export function StageSnapshotCard({ stageNo, reachedIdx, result, question, cfg }: Props) {
  const idx = Number(stageNo) - 1

  if (idx > reachedIdx) {
    return (
      <section className="snapshot-card">
        <div className="snapshot-card-head">
          <h2 className="snapshot-card-title">{TITLE[stageNo]}</h2>
        </div>
        <div className="snapshot-card-body">
          <p className="snapshot-empty-text">이전 단계에서 멈춰 이 단계는 실행되지 않았습니다.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="snapshot-card">
      <div className="snapshot-card-head">
        <h2 className="snapshot-card-title">{TITLE[stageNo]}</h2>
      </div>
      <div className="snapshot-card-body">{renderBody(stageNo, result, question, cfg)}</div>
    </section>
  )
}

function renderBody(stageNo: string, result: RunResult, question: string, cfg: ReviewConfig) {
  switch (stageNo) {
    case '1':
      return (
        <div className="running-block">
          <span className="review-section-label">INPUT QUESTION</span>
          <p className="running-question-box">{question}</p>
          <div className="intent-summary-row">
            {result.difficulty && <span className="pill pill-difficulty">난이도 {result.difficulty}</span>}
            {result.task_type && <span className="pill">{result.task_type}</span>}
          </div>
        </div>
      )
    case '2':
      return (
        <div className="running-block">
          <CandidateList candidates={result.schema_candidate_details} />
          {cfg.schema ? (
            <>
              <span className="review-section-hint">승인된 테이블</span>
              <ul className="snapshot-list">
                {result.confirmed_schema.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </>
          ) : (
            <p className="snapshot-empty-text">검토 모드가 꺼져 있어 자동 승인됐습니다.</p>
          )}
        </div>
      )
    case '3':
      return result.sql ? (
        <div className="running-block">
          <pre className="sql-view-box">{result.sql}</pre>
          <p className="snapshot-empty-text">
            {cfg.sql ? '검토를 거쳐 승인된 SQL입니다.' : '검토 모드가 꺼져 있어 자동 승인됐습니다.'}
          </p>
        </div>
      ) : (
        <p className="snapshot-empty-text">값을 확정하지 못해 SQL을 생성하지 못했습니다.</p>
      )
    case '4':
      return <ValidateChecklist result={result} />
    case '5':
      return result.row_count != null ? (
        <p className="snapshot-empty-text">
          {result.row_count}행 · {result.latency_ms}ms — 아래 실행 결과 카드를 참고하세요.
        </p>
      ) : (
        <p className="snapshot-empty-text">실행되지 않았습니다.</p>
      )
    default:
      return null
  }
}
