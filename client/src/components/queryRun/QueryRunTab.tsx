import { useEffect, useRef, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import { runsApi } from '../../api/runsClient'
import type { LogLine, ReviewConfig, RunResult } from '../../types'
import { ExecutionLogPanel } from './ExecutionLogPanel'
import { TurnCard } from './TurnCard'
import { useRunReview } from './useRunReview'
import type { Phase } from './stages'

export function QueryRunTab() {
  const [domainName, setDomainName] = useState<string | null>(null)
  const [pendingCfg, setPendingCfg] = useState<ReviewConfig>({ schema: false, sql: false })
  const [question, setQuestion] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)

  // 대화(스레드) 상태 — 완료된 과거 턴은 turns에 얼려두고, 지금 진행 중이거나 검토 대기인
  // "라이브" 턴 하나만 useRunReview가 담당한다. conversationId가 없으면 아직 이 화면에서
  // 한 번도 실행하지 않은 새 대화다.
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [turns, setTurns] = useState<RunResult[]>([])
  const [collapsedOverride, setCollapsedOverride] = useState<Record<number, boolean>>({})
  const [carryContext, setCarryContext] = useState(true)
  const [liveQuestion, setLiveQuestion] = useState('')

  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const {
    phase, result, error, cfg,
    schemaChecked, sqlDraft, setSqlDraft, sqlDraftEdited, correctionReason, setCorrectionReason,
    toggleSchemaCandidate,
    goToPhase, loadResult, approveSchema, approveSql, reset,
    isRunning, currentNode, liveLogs,
  } = useRunReview(pendingCfg)

  useEffect(() => {
    domainApi
      .status()
      .then((s) => setDomainName(s.domain))
      .catch(() => setDomainName(null))
  }, [])

  const hasLiveTurn = phase !== 'idle'
  const liveTurnNo = result?.turn_no ?? turns.length + 1
  const totalTurns = turns.length + (hasLiveTurn ? 1 : 0)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [totalTurns, phase])

  const runQuery = async () => {
    const q = question.trim()
    if (!q) return
    setSubmitError(null)
    // 직전 턴이 이미 끝나 있었으면(성공/실패) 대화 목록에 얼려 넣고 새 라이브 턴을 시작한다.
    if (result) {
      setTurns((prev) => [...prev, result])
    }
    setLiveQuestion(q)
    setQuestion('')
    reset()
    // 서버 응답(run_id 포함)이 오기 전부터 진행 상황을 폴링하려면 클라이언트가 미리 run_id를
    // 발급해 보내야 한다 — POST /runs는 동기 호출이라 그 전엔 서버가 만든 run_id를 알 수 없다.
    const runId = crypto.randomUUID()
    goToPhase('running_create', runId)
    try {
      const r = await runsApi.create(
        q,
        domainName ?? undefined,
        pendingCfg,
        conversationId ?? undefined,
        !!conversationId && carryContext,
        runId,
      )
      if (!conversationId) setConversationId(r.conversation_id)
      loadResult(r)
    } catch (e) {
      goToPhase('idle')
      setSubmitError(e instanceof Error ? e.message : '실행 요청 실패')
      setQuestion(q)
    }
  }

  // 지금 진행 중인 턴만 초기화한다 — 대화(conversationId·과거 턴)는 그대로 남아 있어서
  // 실패한 질문을 고쳐 같은 대화 안에서 다시 보낼 수 있다.
  const retryLiveTurn = () => {
    reset()
    setSubmitError(null)
  }

  const newConversation = () => {
    reset()
    setSubmitError(null)
    setTurns([])
    setConversationId(null)
    setCollapsedOverride({})
    setCarryContext(true)
    setLiveQuestion('')
    setQuestion('')
  }

  const onToggleGate = (key: 'schema' | 'sql') => {
    setPendingCfg((c) => ({ ...c, [key]: !c[key] }))
  }

  const isCollapsed = (turnNo: number, defaultCollapsed: boolean) =>
    collapsedOverride[turnNo] ?? defaultCollapsed
  const toggleCollapsed = (turnNo: number, defaultCollapsed: boolean) =>
    setCollapsedOverride((prev) => ({ ...prev, [turnNo]: !isCollapsed(turnNo, defaultCollapsed) }))

  const blocked = isRunning || phase === 'schema_review' || phase === 'sql_review'
  // 실행 중(isRunning)에는 위쪽 스테이지 레일·러닝 카드에 이미 진행 상황이 보이므로 별도
  // 안내 배너를 띄우지 않는다 — 검토 대기 중일 때만, 왜 입력이 막혔는지 설명이 필요하다.
  const blockedLabel = `턴 ${liveTurnNo}이 검토 대기 중입니다. 승인 또는 취소 후 다음 질문을 보낼 수 있습니다.`
  const placeholder = blocked
    ? '검토를 완료해야 다음 질문을 할 수 있습니다'
    : conversationId
      ? '이어서 질문하세요 — 이전 턴의 결과와 스키마를 컨텍스트로 사용합니다'
      : '질문을 입력하세요'

  // 실행 중인 라운드는 result.logs가 아니라 진행 중 폴링으로 받은 liveLogs를 쓴다 —
  // 서버가 이미 직전 라운드 로그 + 이번 라운드 진행분을 합쳐서 주므로(run_routes.py의
  // /progress), 실행이 끝나면 자연히 result.logs와 같은 내용이 된다.
  const liveTurnLogs = isRunning
    ? liveLogs.map((l) => ({ ...l, turn: liveTurnNo }))
    : result
      ? result.logs.map((l) => ({ ...l, turn: result.turn_no }))
      : []

  const allLogs: LogLine[] = [
    ...turns.flatMap((t) => t.logs.map((l) => ({ ...l, turn: t.turn_no }))),
    ...liveTurnLogs,
  ]

  return (
    <div className="query-run-shell">
      <header className="page-header">
        <h1>질의 실행</h1>
        <div className="header-spacer" />
        <button
          className="btn-secondary"
          onClick={newConversation}
          disabled={!conversationId && totalTurns === 0}
        >
          새 대화
        </button>
        <span className="header-domain-label">domain</span>
        <span className="header-domain-value">{domainName ?? '—'}</span>
      </header>

      <div className="turn-list-scroll" ref={scrollRef}>
        {totalTurns === 0 && (
          <p className="turn-empty-placeholder">질문을 입력하면 대화가 여기에 시작됩니다.</p>
        )}

        {turns.map((t) => {
          const frozenPhase: Phase = t.status === 'success' ? 'done' : 'failed'
          const collapsed = isCollapsed(t.turn_no, true)
          return (
            <TurnCard
              key={t.run_id}
              turnNo={t.turn_no}
              question={t.question}
              result={t}
              phase={frozenPhase}
              cfg={t.review_config}
              isLive={false}
              collapsed={collapsed}
              onToggleCollapse={() => toggleCollapsed(t.turn_no, true)}
            />
          )
        })}

        {hasLiveTurn && (
          <TurnCard
            key={result?.run_id ?? 'live'}
            turnNo={liveTurnNo}
            question={result?.question ?? liveQuestion}
            result={result}
            phase={phase}
            cfg={cfg}
            isLive
            currentNode={currentNode}
            collapsed={isCollapsed(liveTurnNo, false)}
            onToggleCollapse={() => toggleCollapsed(liveTurnNo, false)}
            live={{
              schemaChecked,
              onToggleSchemaCandidate: toggleSchemaCandidate,
              onCancelSchema: retryLiveTurn,
              onApproveSchema: approveSchema,
              sqlDraft,
              setSqlDraft,
              sqlDraftEdited,
              correctionReason,
              setCorrectionReason,
              onApproveSql: approveSql,
              onRestartFailed: retryLiveTurn,
            }}
            onFollowUp={phase === 'done' ? () => textareaRef.current?.focus() : undefined}
          />
        )}
      </div>

      <div className="composer-footer">
        {(submitError || error) && <div className="run-error-banner">{submitError ?? error}</div>}

        {(phase === 'schema_review' || phase === 'sql_review') && (
          <div className="composer-blocked-banner">
            <span className="composer-blocked-mark">!</span>
            <span className="composer-blocked-text">{blockedLabel}</span>
          </div>
        )}

        <div className="composer-input-row">
          <textarea
            ref={textareaRef}
            className="run-question-input"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            disabled={blocked}
            placeholder={placeholder}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                runQuery()
              }
            }}
          />
          <button
            className="btn-primary run-button"
            onClick={runQuery}
            disabled={blocked || !question.trim()}
          >
            전송
          </button>
        </div>

        <div className="composer-config-row">
          <span className="composer-config-label">다음 질문에 적용</span>
          <label className="composer-checkbox">
            <input type="checkbox" checked={pendingCfg.schema} onChange={() => onToggleGate('schema')} />
            <span>스키마 검토</span>
          </label>
          <label className="composer-checkbox">
            <input type="checkbox" checked={pendingCfg.sql} onChange={() => onToggleGate('sql')} />
            <span>SQL 검토</span>
          </label>
          <label className={`composer-checkbox ${conversationId ? '' : 'disabled'}`}>
            <input
              type="checkbox"
              checked={carryContext}
              disabled={!conversationId}
              onChange={() => setCarryContext((v) => !v)}
            />
            <span>이전 턴 스키마 재사용</span>
          </label>
          <div className="header-spacer" />
          <span className="composer-thread-label">
            POST /runs · thread_id {conversationId ? conversationId.slice(0, 8) : '—'}
          </span>
        </div>

        <ExecutionLogPanel logs={allLogs} isRunning={isRunning} countSuffix={totalTurns > 1 ? ` · ${totalTurns} turns` : ''} />
      </div>
    </div>
  )
}
