import { useEffect, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import { runsApi } from '../../api/runsClient'
import type { ReviewConfig } from '../../types'
import { FailedCard } from './FailedCard'
import { ResultCard } from './ResultCard'
import { RunningWorkCard } from './RunningWorkCard'
import { SchemaReviewCard } from './SchemaReviewCard'
import { SqlReviewCard } from './SqlReviewCard'
import { StageRail } from './StageRail'
import { StageSnapshotCard } from './StageSnapshotCard'
import { useRunReview } from './useRunReview'
import { RUNNING_STAGE_NO, type Phase, type RunningPhase } from './stages'

function statusLabel(phase: Phase): string {
  if (phase.startsWith('running_')) return `진행 중 · ${RUNNING_STAGE_NO[phase as RunningPhase]}단계부터`
  if (phase === 'schema_review' || phase === 'sql_review') return '검토 대기'
  if (phase === 'done') return '완료'
  if (phase === 'failed') return '실패'
  return '대기'
}

export function QueryRunTab() {
  const [domainName, setDomainName] = useState<string | null>(null)
  const [pendingCfg, setPendingCfg] = useState<ReviewConfig>({ schema: false, sql: true })
  const [question, setQuestion] = useState(
    '2023년 이후 로봇 수술을 받은 전립선암 환자 수를 Gleason 위험군별로 알려줘',
  )
  const [submitError, setSubmitError] = useState<string | null>(null)

  const {
    phase, result, error, cfg,
    schemaChecked, sqlDraft, setSqlDraft, sqlDraftEdited, correctionReason, setCorrectionReason,
    toggleSchemaCandidate,
    goToPhase, loadResult, approveSchema, approveSql, reset,
    stages, isRunning, viewedStageNo, reachedIdx, showSnapshot, onSelectStage,
  } = useRunReview(pendingCfg)

  useEffect(() => {
    domainApi
      .status()
      .then((s) => setDomainName(s.domain))
      .catch(() => setDomainName(null))
  }, [])

  const runQuery = async () => {
    setSubmitError(null)
    reset()
    goToPhase('running_create')
    try {
      const r = await runsApi.create(question, domainName ?? undefined, pendingCfg)
      loadResult(r)
    } catch (e) {
      goToPhase('idle')
      setSubmitError(e instanceof Error ? e.message : '실행 요청 실패')
    }
  }

  const restart = () => {
    reset()
    setSubmitError(null)
  }

  const onToggleGate = (key: 'schema' | 'sql') => {
    setPendingCfg((c) => ({ ...c, [key]: !c[key] }))
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

        {(submitError || error) && <div className="run-error-banner">{submitError ?? error}</div>}

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
            <div className="header-spacer" />
            <span className="review-config-label">
              review_config {`{ schema: ${cfg.schema}, sql: ${cfg.sql} }`}
            </span>
          </div>

          {result && (
            <div className="intent-summary-row">
              <span className="review-section-label">1단계 결과 · INTENT</span>
              {result.difficulty && <span className="pill pill-difficulty">난이도 {result.difficulty}</span>}
              {result.task_type && <span className="pill">{result.task_type}</span>}
            </div>
          )}

          <StageRail
            stages={stages}
            cfg={cfg}
            onToggleGate={onToggleGate}
            selectedNo={viewedStageNo}
            onSelect={onSelectStage}
          />

          {result && result.retries > 0 && (
            <div className="retry-note">
              ↺ 검증/생성 재시도 {result.retries}회 발생 — 최종적으로{' '}
              {result.status === 'success' ? '통과했습니다.' : '실패했습니다.'}
            </div>
          )}
        </section>

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
            onToggle={toggleSchemaCandidate}
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
            edited={sqlDraftEdited}
            correctionReason={correctionReason}
            onCorrectionReasonChange={setCorrectionReason}
            onApprove={approveSql}
          />
        )}

        {phase === 'done' && result && <ResultCard result={result} />}

        {phase === 'failed' && result && <FailedCard result={result} onRestart={restart} />}
      </div>
    </>
  )
}
