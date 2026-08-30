import { useEffect, useState } from 'react'
import { runsApi } from '../../api/runsClient'
import { FailedCard } from '../queryRun/FailedCard'
import { ResultCard } from '../queryRun/ResultCard'
import { RunningWorkCard } from '../queryRun/RunningWorkCard'
import { SchemaReviewCard } from '../queryRun/SchemaReviewCard'
import { SqlReviewCard } from '../queryRun/SqlReviewCard'
import { StageRail } from '../queryRun/StageRail'
import { StageSnapshotCard } from '../queryRun/StageSnapshotCard'
import type { RunningPhase } from '../queryRun/stages'
import { useRunReview } from '../queryRun/useRunReview'
import { formatRelativeTime } from './relativeTime'
import { STATUS_CLASS, STATUS_LABEL } from './runStatus'

interface Props {
  runId: string | null
  createdAt: string | null // 목록에서 이미 알고 있는 생성 시각 — RunResult 자체엔 없어 목록 쪽에서 받는다
  onAfterResume: () => void // 재개로 상태가 바뀌었으니 목록도 최신 상태를 다시 읽어야 한다는 신호
  onClose: () => void
}

/** POST /runs가 동기 블로킹이라 정상적으로는 거의 관측되지 않는 상태(다른 세션이 같은 run을
 * 돌리고 있거나, 프로세스가 죽어 _mark_crashed도 못 탄 경우)만 여기 해당한다. 실시간 스트리밍이
 * 없는 구조에서 가짜 폴링 UI를 만드는 대신 정직하게 안내만 한다. */
function RunningPlaceholder({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="panel history-placeholder">
      다른 세션에서 아직 처리 중인 run입니다 — 여기서 실시간으로 따라갈 수는 없습니다.
      <button className="btn-secondary" onClick={onRetry}>새로고침</button>
    </section>
  )
}

export function RunDetailPanel({ runId, createdAt, onAfterResume, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [stillRunning, setStillRunning] = useState(false)
  const [fetchToken, setFetchToken] = useState(0)

  const {
    phase, result, error, cfg,
    schemaChecked, sqlDraft, setSqlDraft, sqlDraftEdited, correctionReason, setCorrectionReason,
    toggleSchemaCandidate,
    loadResult, approveSchema, approveSql,
    stages, isRunning, viewedStageNo, reachedIdx, showSnapshot, onSelectStage,
  } = useRunReview()

  useEffect(() => {
    if (!runId) return
    setLoading(true)
    setLoadError(null)
    setStillRunning(false)
    runsApi
      .get(runId)
      .then((r) => {
        // create()가 registry 행을 만든 직후라 아직 state_snapshot이 채워지지 않은 경우 —
        // _finalize()가 한 번도 안 돌았으면 run_id 필드조차 없다.
        if (!r.run_id) {
          setStillRunning(true)
          return
        }
        loadResult(r)
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : '조회 실패'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, fetchToken])

  const approveAndRefresh = async (fn: () => Promise<void>) => {
    await fn()
    onAfterResume()
  }

  if (!runId) {
    return (
      <section className="panel history-placeholder">왼쪽 목록에서 실행을 선택하세요.</section>
    )
  }

  if (loading && !result) {
    return <section className="panel history-placeholder">불러오는 중…</section>
  }

  if (loadError) {
    return (
      <section className="panel history-placeholder">
        {loadError}
        <button className="btn-secondary" onClick={() => setFetchToken((t) => t + 1)}>다시 시도</button>
      </section>
    )
  }

  if (stillRunning) {
    return <RunningPlaceholder onRetry={() => setFetchToken((t) => t + 1)} />
  }

  if (!result) return null

  return (
    <div className="history-detail">
      <section className="panel history-detail-head">
        <div className="history-detail-head-row">
          <h2>{result.run_id.slice(0, 8)}</h2>
          <span className={`run-status-badge ${STATUS_CLASS[result.status]}`}>{STATUS_LABEL[result.status]}</span>
          <span className="history-detail-meta">
            {createdAt ? formatRelativeTime(createdAt) : ''} · {(result.latency_ms / 1000).toFixed(1)}s
          </span>
          <div className="header-spacer" />
          <span className="review-config-label">
            review_config {`{ schema: ${cfg.schema}, sql: ${cfg.sql} }`} · GET /runs/{result.run_id}
          </span>
        </div>

        <p className="history-detail-question">{result.question}</p>

        <div className="intent-summary-row">
          <span className="review-section-label">INTENT</span>
          {result.difficulty && <span className="pill pill-difficulty">난이도 {result.difficulty}</span>}
          {result.task_type && <span className="pill">{result.task_type}</span>}
          <span className="review-section-hint">domain {result.domain}</span>
        </div>

        <StageRail
          stages={stages}
          cfg={cfg}
          onToggleGate={() => {}}
          readOnly
          selectedNo={viewedStageNo}
          onSelect={onSelectStage}
        />
      </section>

      {error && <div className="run-error-banner">{error}</div>}

      {showSnapshot && viewedStageNo && (
        <StageSnapshotCard
          stageNo={viewedStageNo}
          reachedIdx={reachedIdx}
          result={result}
          question={result.question}
          cfg={cfg}
        />
      )}

      {!showSnapshot && isRunning && <RunningWorkCard phase={phase as RunningPhase} />}

      {!showSnapshot && phase === 'schema_review' && (
        <SchemaReviewCard
          candidates={result.schema_candidate_details}
          checked={schemaChecked}
          onToggle={toggleSchemaCandidate}
          onCancel={onClose}
          onApprove={() => approveAndRefresh(approveSchema)}
        />
      )}

      {!showSnapshot && phase === 'sql_review' && (
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
          onApprove={() => approveAndRefresh(approveSql)}
        />
      )}

      {!showSnapshot && phase === 'done' && <ResultCard result={result} />}

      {!showSnapshot && phase === 'failed' && <FailedCard result={result} onRestart={onClose} />}
    </div>
  )
}
