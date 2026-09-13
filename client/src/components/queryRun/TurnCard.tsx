import type { ReviewConfig, RunResult } from '../../types'
import { FailedCard } from './FailedCard'
import { ResultCard } from './ResultCard'
import { RunningWorkCard } from './RunningWorkCard'
import { SchemaReviewCard } from './SchemaReviewCard'
import { SqlReviewCard } from './SqlReviewCard'
import { StageRail } from './StageRail'
import { computeStages, isRunningPhase, type Phase } from './stages'

const STATUS_LABEL: Record<string, string> = {
  running: '실행 중',
  interrupted_schema: '검토 대기(스키마)',
  interrupted_sql: '검토 대기(SQL)',
  success: '성공',
  error: '실패',
}

// 진행 중인(라이브) 턴에서만 필요한 검토/재개 핸들러 — 이미 끝난 과거 턴은 다시 손댈 수 없다.
interface LiveReview {
  schemaChecked: Record<string, boolean>
  columnChecked: Record<string, Record<string, boolean>>
  onToggleSchemaCandidate: (table: string) => void
  onToggleColumn: (table: string, column: string) => void
  onCancelSchema: () => void
  onApproveSchema: () => void
  sqlDraft: string
  setSqlDraft: (v: string) => void
  sqlDraftEdited: boolean
  correctionReason: string
  setCorrectionReason: (v: string) => void
  onApproveSql: () => void
  onRestartFailed: () => void
}

interface Props {
  turnNo: number
  question: string
  result: RunResult | null
  phase: Phase
  cfg: ReviewConfig
  isLive: boolean
  collapsed: boolean
  onToggleCollapse: () => void
  live?: LiveReview
  onFollowUp?: () => void
}

const noopToggleGate = () => {}

function collapsedSummaryOf(phase: Phase, result: RunResult | null): string {
  if (!result) return isRunningPhase(phase) ? '진행 중…' : '검토 대기 중'
  if (result.status === 'success') return (result.summary ?? '').replace(/\s+/g, ' ').trim().slice(0, 100)
  if (result.status === 'error') return result.retry_feedback ?? result.execution_error ?? '실패'
  return '검토 대기 중'
}

/** 대화 스레드 안의 턴 하나 — 접으면 질문+한줄 요약만, 펼치면 기존 단일 실행 화면과 동일한
 * 스테이지 레일 + 단계별 카드를 그대로 보여준다. isLive가 아닌 턴은 이미 종료된(success/error)
 * 상태만 오므로 검토 카드가 뜰 일이 없다 — live만 SchemaReviewCard/SqlReviewCard를 받는다. */
export function TurnCard({
  turnNo, question, result, phase, cfg, isLive, collapsed, onToggleCollapse, live, onFollowUp,
}: Props) {
  const stages = computeStages(phase, cfg, result)
  const statusKey = isRunningPhase(phase)
    ? 'running'
    : phase === 'schema_review'
      ? 'interrupted_schema'
      : phase === 'sql_review'
        ? 'interrupted_sql'
        : phase === 'failed'
          ? 'error'
          : 'success'

  return (
    <section className={`turn-card ${isLive ? 'active' : ''}`}>
      <div className="turn-card-head" onClick={onToggleCollapse} role="button" tabIndex={0}>
        <span className={`turn-chip ${isLive ? 'live' : ''}`}>턴 {turnNo}</span>
        <div className="turn-head-main">
          <p className="turn-question">{question}</p>
          {turnNo > 1 && <span className="turn-context-hint">↑ 이전 턴 컨텍스트 사용</span>}
        </div>
        <div className="turn-head-side">
          <span className={`run-status-badge status-${statusKey}`}>{STATUS_LABEL[statusKey]}</span>
          {result && <span className="turn-run-id">{result.run_id.slice(0, 8)}</span>}
          <span className="turn-chevron">{collapsed ? '›' : '⌄'}</span>
        </div>
      </div>

      {collapsed && (
        <div className="turn-collapsed-row">
          <span className="turn-collapsed-summary">{collapsedSummaryOf(phase, result)}</span>
          {result?.row_count != null && (
            <span className="turn-collapsed-meta">
              {result.row_count}행 · {result.latency_ms}ms
            </span>
          )}
        </div>
      )}

      {!collapsed && (
        <div className="turn-body">
          {result && (
            <div className="intent-summary-row">
              <span className="review-section-label">INTENT</span>
              {result.difficulty && <span className="pill pill-difficulty">난이도 {result.difficulty}</span>}
              {result.task_type && <span className="pill">{result.task_type}</span>}
              <div className="header-spacer" />
              <span className="review-config-label">
                review_config {`{ schema: ${cfg.schema}, sql: ${cfg.sql} }`}
              </span>
            </div>
          )}

          <StageRail stages={stages} cfg={cfg} onToggleGate={noopToggleGate} readOnly />

          {isRunningPhase(phase) && <RunningWorkCard phase={phase} />}

          {phase === 'schema_review' && result && live && (
            <SchemaReviewCard
              candidates={result.schema_candidate_details}
              checked={live.schemaChecked}
              onToggle={live.onToggleSchemaCandidate}
              columnChecked={live.columnChecked}
              onToggleColumn={live.onToggleColumn}
              onCancel={live.onCancelSchema}
              onApprove={live.onApproveSchema}
            />
          )}

          {phase === 'sql_review' && result && live && (
            <SqlReviewCard
              sql={live.sqlDraft}
              onChange={live.setSqlDraft}
              retries={result.retries}
              runId={result.run_id}
              refTables={result.confirmed_schema}
              retryErrorCode={result.retry_error_code}
              retryFeedback={result.retry_feedback}
              edited={live.sqlDraftEdited}
              correctionReason={live.correctionReason}
              onCorrectionReasonChange={live.setCorrectionReason}
              onApprove={live.onApproveSql}
            />
          )}

          {phase === 'failed' && result && (
            <FailedCard result={result} onRestart={live?.onRestartFailed ?? noopToggleGate} />
          )}

          {phase === 'done' && result && (
            <>
              <ResultCard result={result} />
              {onFollowUp && (
                <button className="btn-follow-up" onClick={onFollowUp}>
                  이 결과로 이어서 질문
                </button>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
