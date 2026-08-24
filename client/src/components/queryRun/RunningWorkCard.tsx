import type { RunResult } from '../../types'
import { CandidateList } from './CandidateList'
import { RUNNING_STAGE_NO, RUNNING_STAGE_SUB, RUNNING_STAGE_TITLE, type RunningPhase } from './stages'
import { ValidateChecklist } from './ValidateChecklist'

interface Props {
  phase: RunningPhase
  question: string
  result: RunResult | null
}

/** 실제 백엔드는 POST /runs 동기 호출 하나뿐이라 노드별 실시간 스트리밍은 없다.
 * running_intent는 실제로 응답을 기다리는 동안 보여주고(질문은 이미 알고 있으므로 진짜),
 * 나머지 4단계는 응답이 도착한 뒤 실제 결과 데이터를 짧은 간격으로 리플레이하는 방식이다
 * (QueryRunTab의 playSequence 참고) — 내용은 전부 실데이터, 다만 "그 순간에 진행 중"이라는
 * 타이밍만 연출이다. */
export function RunningWorkCard({ phase, question, result }: Props) {
  return (
    <section className="running-card">
      <div className="running-card-head">
        <span className="running-spinner" />
        <h2 className="running-card-title">
          {RUNNING_STAGE_TITLE[phase]} — {RUNNING_STAGE_NO[phase]}단계
        </h2>
        <p className="running-card-sub">{RUNNING_STAGE_SUB[phase]}</p>
        <div className="review-card-spacer" />
        <span className="review-section-hint">폴링 중 · 1s 간격</span>
      </div>

      <div className="running-card-body">
        {phase === 'running_intent' && (
          <div className="running-block">
            <span className="review-section-label">INPUT QUESTION</span>
            <p className="running-question-box">{question}</p>
            <div className="running-inline-status">
              <span className="running-inline-dot" />
              <span className="running-inline-text">난이도 · 질의유형 분류 중…</span>
            </div>
          </div>
        )}

        {phase === 'running_schema' && (
          <div className="running-block">
            <span className="review-section-label">검색된 후보 테이블</span>
            <CandidateList candidates={result?.schema_candidate_details ?? []} live />
          </div>
        )}

        {phase === 'running_sql' && (
          <div className="running-block">
            <div className="sql-review-label-row">
              <span className="review-section-label">GENERATING SQL</span>
              <div className="review-card-spacer" />
              <span className="review-section-hint">참조 테이블 {(result?.confirmed_schema ?? []).join(', ') || '—'}</span>
            </div>
            {result?.sql ? (
              <>
                <pre className="sql-view-box">{result.sql.split('\n').slice(0, 6).join('\n')}</pre>
                <span className="running-inline-text">생성 중…</span>
              </>
            ) : (
              <span className="running-inline-text">값을 확정하지 못해 SQL을 생성하지 못했습니다…</span>
            )}
          </div>
        )}

        {phase === 'running_validate' && result && <ValidateChecklist result={result} live />}

        {phase === 'running_exec' && (
          <div className="running-block">
            <span className="review-section-label">EXECUTING SQL</span>
            <pre className="sql-view-box">{result?.sql ?? ''}</pre>
            <span className="running-inline-text">읽기 전용 커넥션 · 실행 대기 중…</span>
          </div>
        )}
      </div>
    </section>
  )
}
