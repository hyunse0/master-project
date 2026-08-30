import { useEffect, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import { runsApi } from '../../api/runsClient'
import type { ReviewConfig, RunResult } from '../../types'
import { FailedCard } from './FailedCard'
import { ResultCard } from './ResultCard'
import { RunningWorkCard } from './RunningWorkCard'
import { SchemaReviewCard } from './SchemaReviewCard'
import { SqlReviewCard } from './SqlReviewCard'
import { StageRail } from './StageRail'
import { StageSnapshotCard } from './StageSnapshotCard'
import {
  activeStageIndex,
  computeStages,
  isRunningPhase,
  RUNNING_STAGE_NO,
  type Phase,
  type RunningPhase,
} from './stages'

const MODES: { label: string; cfg: ReviewConfig | null }[] = [
  { label: '자동', cfg: { schema: false, sql: false } },
  { label: '단계별 검토', cfg: { schema: true, sql: true } },
  { label: '직접 설정', cfg: null },
]

function modeName(cfg: ReviewConfig): string {
  if (!cfg.schema && !cfg.sql) return '자동'
  if (cfg.schema && cfg.sql) return '단계별 검토'
  return '직접 설정'
}

function statusLabel(phase: Phase): string {
  if (phase.startsWith('running_')) return `진행 중 · ${RUNNING_STAGE_NO[phase as RunningPhase]}단계부터`
  if (phase === 'schema_review' || phase === 'sql_review') return '검토 대기'
  if (phase === 'done') return '완료'
  if (phase === 'failed') return '실패'
  return '대기'
}

export function QueryRunTab() {
  const [domainName, setDomainName] = useState<string | null>(null)
  const [cfg, setCfg] = useState<ReviewConfig>({ schema: false, sql: true })
  const [question, setQuestion] = useState(
    '2023년 이후 로봇 수술을 받은 전립선암 환자 수를 Gleason 위험군별로 알려줘',
  )
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [schemaChecked, setSchemaChecked] = useState<Record<string, boolean>>({})
  const [sqlDraft, setSqlDraft] = useState('')
  // 사용자가 스테이지 레일에서 직접 클릭해 들여다보고 있는 단계 — null이면 실시간 진행을 따라간다.
  const [selectedStageNo, setSelectedStageNo] = useState<string | null>(null)

  // 진행이 한 단계 나아갈 때마다, 사용자가 보고 있던 스냅샷은 실시간 화면으로 되돌린다 —
  // 검토 승인이 필요한 순간에 엉뚱한 과거 단계를 보고 있다가 놓치는 일이 없도록 한다.
  const goToPhase = (p: Phase) => {
    setSelectedStageNo(null)
    setPhase(p)
  }

  useEffect(() => {
    domainApi
      .status()
      .then((s) => setDomainName(s.domain))
      .catch(() => setDomainName(null))
  }, [])

  /** POST /runs·resume 응답의 status를 보고 다음에 보여줄 화면을 정한다 — 전부 서버가
   * 실제로 멈춘 지점을 그대로 반영한 것이지 클라이언트가 지어내는 게 아니다. */
  const enterFromResult = (r: RunResult) => {
    if (r.status === 'interrupted_schema') {
      setSchemaChecked(Object.fromEntries(r.schema_candidates.map((t) => [t, true])))
      goToPhase('schema_review')
      return
    }
    if (r.status === 'interrupted_sql') {
      setSqlDraft(r.sql ?? '')
      goToPhase('sql_review')
      return
    }
    goToPhase(r.status === 'success' ? 'done' : 'failed')
  }

  const runQuery = async () => {
    setError(null)
    setResult(null)
    goToPhase('running_create')
    try {
      const r = await runsApi.create(question, domainName ?? undefined, cfg)
      setResult(r)
      enterFromResult(r)
    } catch (e) {
      goToPhase('idle')
      setError(e instanceof Error ? e.message : '실행 요청 실패')
    }
  }

  const approveSchema = async () => {
    if (!result) return
    const confirmed = result.schema_candidate_details
      .map((c) => c.table)
      .filter((t) => schemaChecked[t])
    goToPhase('running_after_schema')
    try {
      const r = await runsApi.resume(result.run_id, { confirmed_schema: confirmed })
      setResult(r)
      enterFromResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'resume 요청 실패')
      goToPhase('schema_review')
    }
  }

  const approveSql = async () => {
    if (!result) return
    goToPhase('running_after_sql')
    try {
      const r = await runsApi.resume(result.run_id, { sql: sqlDraft })
      setResult(r)
      enterFromResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'resume 요청 실패')
      goToPhase('sql_review')
    }
  }

  const restart = () => {
    goToPhase('idle')
    setResult(null)
    setError(null)
  }

  const stages = computeStages(phase, cfg, result)
  const showProgress = phase !== 'idle'
  const isRunning = isRunningPhase(phase)

  const activeIdx = activeStageIndex(phase, result)
  const activeStageNo = phase === 'done' ? '7' : activeIdx >= 0 && activeIdx <= 6 ? String(activeIdx + 1) : null
  const reachedIdx = phase === 'done' ? 6 : activeIdx
  const viewedStageNo = selectedStageNo ?? activeStageNo
  const showSnapshot = !!viewedStageNo && viewedStageNo !== activeStageNo && !!result

  const onSelectStage = (no: string) => {
    setSelectedStageNo(no === activeStageNo ? null : no)
  }

  return (
    <>
      <header className="page-header">
        <h1>질의 실행</h1>
        <p className="subtitle">자연어 질문을 SQL로 변환해 실행합니다.</p>
        <div className="header-spacer" />
        <span className="header-domain-label">domain</span>
        <span className="header-domain-value">{domainName ?? '—'}</span>
      </header>

      <div className="content">
        <section className="run-input-card">
          <div className="run-input-top">
            <span className="run-input-label">검토 모드</span>
            <div className="mode-toggle">
              {MODES.map((m) => (
                <button
                  key={m.label}
                  className={modeName(cfg) === m.label ? 'active' : ''}
                  onClick={() => m.cfg && setCfg(m.cfg)}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <div className="run-input-checks">
              <label>
                <input
                  type="checkbox"
                  checked={cfg.schema}
                  onChange={() => setCfg((c) => ({ ...c, schema: !c.schema }))}
                />
                <span>스키마 검토</span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={cfg.sql}
                  onChange={() => setCfg((c) => ({ ...c, sql: !c.sql }))}
                />
                <span>SQL 검토</span>
              </label>
            </div>
          </div>

          <div className="run-input-divider" />

          <div className="run-input-row">
            <textarea
              className="run-question-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="예: 2023년 이후 로봇 수술을 받은 전립선암 환자 수를 Gleason 위험군별로 알려줘"
            />
            <button
              className="btn-primary run-button"
              onClick={runQuery}
              disabled={isRunning || !question.trim()}
            >
              실행
            </button>
          </div>
        </section>

        {error && <div className="run-error-banner">{error}</div>}

        {showProgress && (
          <section className="progress-card">
            <div className="progress-head">
              <h2>진행 상태</h2>
              <span className={`run-status-badge status-${isRunning ? 'fetching' : phase}`}>
                {statusLabel(phase)}
              </span>
              {result && result.retries > 0 && (
                <span className="retry-badge">
                  검증 재시도 {result.retries}/{result.max_retries}
                </span>
              )}
            </div>

            {result && (
              <div className="intent-summary-row">
                <span className="review-section-label">1단계 결과 · INTENT</span>
                {result.difficulty && <span className="pill pill-difficulty">난이도 {result.difficulty}</span>}
                {result.task_type && <span className="pill">{result.task_type}</span>}
              </div>
            )}

            <StageRail stages={stages} selectedNo={viewedStageNo} onSelect={onSelectStage} />

            {result && result.retries > 0 && (
              <div className="retry-note">
                ↺ 검증/생성 재시도 {result.retries}회 발생 — 최종적으로{' '}
                {result.status === 'success' ? '통과했습니다.' : '실패했습니다.'}
              </div>
            )}
          </section>
        )}

        {showSnapshot && viewedStageNo && result && (
          <StageSnapshotCard
            stageNo={viewedStageNo}
            reachedIdx={reachedIdx}
            result={result}
            question={question}
            cfg={cfg}
          />
        )}

        {!showSnapshot && isRunning && <RunningWorkCard phase={phase as RunningPhase} />}

        {!showSnapshot && phase === 'schema_review' && result && (
          <SchemaReviewCard
            candidates={result.schema_candidate_details}
            checked={schemaChecked}
            onToggle={(t) => setSchemaChecked((prev) => ({ ...prev, [t]: !prev[t] }))}
            onCancel={restart}
            onApprove={approveSchema}
          />
        )}

        {!showSnapshot && phase === 'sql_review' && result && (
          <SqlReviewCard
            sql={sqlDraft}
            onChange={setSqlDraft}
            retries={result.retries}
            runId={result.run_id}
            refTables={result.confirmed_schema}
            retryErrorCode={result.retry_error_code}
            retryFeedback={result.retry_feedback}
            onApprove={approveSql}
          />
        )}

        {phase === 'done' && result && <ResultCard result={result} />}

        {phase === 'failed' && result && <FailedCard result={result} onRestart={restart} />}
      </div>
    </>
  )
}
