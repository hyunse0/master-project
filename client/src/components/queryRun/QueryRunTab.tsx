import { useEffect, useRef, useState } from 'react'
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
  failedStageIndex,
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
  if (phase.startsWith('running_')) return `진행 중 · ${RUNNING_STAGE_NO[phase as RunningPhase]}단계`
  if (phase === 'schema_review' || phase === 'sql_review') return '검토 대기'
  if (phase === 'done') return '완료'
  if (phase === 'failed') return '실패'
  return '대기'
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

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

  // 스키마/SQL 검토 게이트에서 "승인" 클릭을 기다리는 리플레이 시퀀스를 재개하기 위한 resolver
  const gateResolver = useRef<(() => void) | null>(null)
  const waitForApproval = () => new Promise<void>((resolve) => { gateResolver.current = resolve })
  const resolveGate = () => { gateResolver.current?.(); gateResolver.current = null }

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

  /** POST /runs는 동기 호출 하나뿐이라 노드별 실시간 진행 상황은 실제로 스트리밍되지 않는다.
   * 응답이 도착한 뒤, 실제 결과 데이터를 짧은 간격으로 재생하며 5개 running_* 단계를 순서대로
   * 보여준다 — 내용은 전부 실데이터이고, "지금 이 순간 진행 중"이라는 타이밍만 연출이다.
   * 검토 게이트(스키마/SQL)가 켜져 있으면 사용자가 승인할 때까지 실제로 멈춘다. */
  const playSequence = async (finished: RunResult) => {
    const failIdx = failedStageIndex(finished.retry_error_code)

    goToPhase('running_schema')
    await sleep(900)

    if (cfg.schema) {
      setSchemaChecked(Object.fromEntries(finished.schema_candidates.map((t) => [t, true])))
      goToPhase('schema_review')
      await waitForApproval()
    }

    goToPhase('running_sql')
    await sleep(900)
    if (failIdx === 3) {
      goToPhase('failed') // VALUE_UNCONFIRMED — SQL을 확정하지 못해 검토로 넘어갈 게 없음
      return
    }

    if (cfg.sql) {
      setSqlDraft(finished.sql ?? '')
      goToPhase('sql_review')
      await waitForApproval()
    }

    goToPhase('running_validate')
    await sleep(1000)
    if (failIdx === 5) {
      goToPhase('failed')
      return
    }

    goToPhase('running_exec')
    await sleep(700)
    goToPhase(finished.status === 'success' ? 'done' : 'failed')
  }

  const runQuery = async () => {
    setError(null)
    setResult(null)
    goToPhase('running_intent')
    try {
      const r = await runsApi.create(question, domainName ?? undefined)
      setResult(r)
      await playSequence(r)
    } catch (e) {
      goToPhase('idle')
      setError(e instanceof Error ? e.message : '실행 요청 실패')
    }
  }

  const restart = () => {
    goToPhase('idle')
    setResult(null)
    setError(null)
    gateResolver.current = null
  }

  const editFailedSql = () => {
    if (!result?.sql) return
    setSqlDraft(result.sql)
    goToPhase('sql_review')
  }

  const approveSql = () => {
    // 실패 화면에서 "SQL 직접 수정"으로 들어온 경우 재생 시퀀스가 이미 끝나 있으므로 바로 결과로.
    if (gateResolver.current) resolveGate()
    else if (result) goToPhase(result.status === 'success' ? 'done' : 'failed')
  }

  const stages = computeStages(phase, cfg, result)
  const showProgress = phase !== 'idle'
  const isRunningPhase = phase.startsWith('running_')

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
              disabled={isRunningPhase || !question.trim()}
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
              <span className={`run-status-badge status-${isRunningPhase ? 'fetching' : phase}`}>
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

        {!showSnapshot && isRunningPhase && (
          <RunningWorkCard phase={phase as RunningPhase} question={question} result={result} />
        )}

        {!showSnapshot && phase === 'schema_review' && result && (
          <SchemaReviewCard
            candidates={result.schema_candidate_details}
            checked={schemaChecked}
            onToggle={(t) => setSchemaChecked((prev) => ({ ...prev, [t]: !prev[t] }))}
            onCancel={restart}
            onApprove={resolveGate}
          />
        )}

        {!showSnapshot && phase === 'sql_review' && result && (
          <SqlReviewCard
            sql={sqlDraft}
            onChange={setSqlDraft}
            retries={result.retries}
            runId={result.run_id}
            refTables={result.confirmed_schema}
            onApprove={approveSql}
          />
        )}

        {phase === 'done' && result && <ResultCard result={result} />}

        {phase === 'failed' && result && (
          <FailedCard result={result} onEditSql={editFailedSql} onRestart={restart} />
        )}
      </div>
    </>
  )
}
