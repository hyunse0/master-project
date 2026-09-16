import { useEffect, useState } from 'react'
import { runsApi } from '../../api/runsClient'
import type { LogLine, ReviewConfig, RunResult } from '../../types'
import { activeStageIndex, computeStages, isRunningPhase, type Phase } from './stages'

const PROGRESS_POLL_MS = 800

const IDLE_CFG: ReviewConfig = { schema: false, sql: false }

/** 질의 실행 탭의 "새 질문 실행"과 히스토리 탭의 "과거 run 재개"가 공유하는 검토/재개 로직.
 * 둘 다 결국 RunResult 하나를 받아 같은 스테이지 레일·검토 카드·결과 카드로 렌더링하고,
 * 검토 대기 상태면 같은 POST /runs/{id}/resume으로 이어간다 — 차이는 그 RunResult가
 * POST /runs(신규 실행)에서 왔는지 GET /runs/{id}(과거 run 재조회)에서 왔는지뿐이다. */
export function useRunReview(pendingCfg: ReviewConfig = IDLE_CFG) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [schemaChecked, setSchemaChecked] = useState<Record<string, boolean>>({})
  const [sqlDraft, setSqlDraft] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  // 사용자가 스테이지 레일에서 직접 클릭해 들여다보고 있는 단계 — null이면 실시간 진행을 따라간다.
  const [selectedStageNo, setSelectedStageNo] = useState<string | null>(null)
  // running_* phase 동안 GET /runs/{id}/progress를 폴링해 얻는 실제 실행 중 노드 이름과
  // 지금까지 쌓인 로그 — 로그는 result가 오기 전까지 실행 로그 패널을 실시간으로 채우는 데 쓴다.
  const [pollRunId, setPollRunId] = useState<string | null>(null)
  const [currentNode, setCurrentNode] = useState<string | null>(null)
  const [liveLogs, setLiveLogs] = useState<LogLine[]>([])

  // 진행이 한 단계 나아갈 때마다, 사용자가 보고 있던 스냅샷은 실시간 화면으로 되돌린다 —
  // 검토 승인이 필요한 순간에 엉뚱한 과거 단계를 보고 있다가 놓치는 일이 없도록 한다.
  // running_* phase로 들어갈 때만 pollId를 넘겨 progress 폴링 대상을 지정한다 — 그 외
  // phase에서는 폴링을 멈추고 지난 노드 표시를 지운다.
  const goToPhase = (p: Phase, pollId?: string) => {
    setSelectedStageNo(null)
    setPhase(p)
    if (isRunningPhase(p)) {
      setPollRunId(pollId ?? null)
      setLiveLogs([])
    } else {
      setPollRunId(null)
      setCurrentNode(null)
    }
  }

  useEffect(() => {
    if (!pollRunId) return
    let cancelled = false
    const tick = () => {
      runsApi
        .progress(pollRunId)
        .then((r) => {
          if (cancelled) return
          setCurrentNode(r.current_node)
          setLiveLogs(r.logs)
        })
        .catch(() => {})
    }
    tick()
    const id = setInterval(tick, PROGRESS_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollRunId])

  /** POST /runs·resume 응답이든 GET /runs/{id} 조회 결과든, status를 보고 어느 화면을
   * 보여줄지 정한다 — 전부 서버가 실제로 멈춘 지점을 그대로 반영한 것이지 클라이언트가
   * 지어내는 게 아니다. */
  const loadResult = (r: RunResult) => {
    setResult(r)
    setError(null)
    if (r.status === 'interrupted_schema') {
      setSchemaChecked(Object.fromEntries(r.schema_candidates.map((t) => [t, true])))
      goToPhase('schema_review')
      return
    }
    if (r.status === 'interrupted_sql') {
      setSqlDraft(r.sql ?? '')
      setCorrectionReason('')
      goToPhase('sql_review')
      return
    }
    goToPhase(r.status === 'success' ? 'done' : 'failed')
  }

  const approveSchema = async () => {
    if (!result) return
    const confirmed = result.schema_candidate_details
      .map((c) => c.table)
      .filter((t) => schemaChecked[t])
    goToPhase('running_after_schema', result.run_id)
    try {
      const r = await runsApi.resume(result.run_id, { confirmed_schema: confirmed })
      loadResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'resume 요청 실패')
      goToPhase('schema_review')
    }
  }

  // 서버가 보여준 SQL과 지금 편집창의 SQL이 다르면 사람이 실제로 손댄 것 — 이때만 "수정 이유"
  // 입력창을 보여주고 서버로도 같이 보낸다(서버도 어차피 같은 비교를 다시 해서 확인한다).
  const sqlDraftEdited = !!result && sqlDraft !== (result.sql ?? '')

  const approveSql = async () => {
    if (!result) return
    goToPhase('running_after_sql', result.run_id)
    try {
      const r = await runsApi.resume(result.run_id, {
        sql: sqlDraft,
        correction_reason: sqlDraftEdited && correctionReason.trim() ? correctionReason.trim() : undefined,
      })
      loadResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'resume 요청 실패')
      goToPhase('sql_review')
    }
  }

  const reset = () => {
    goToPhase('idle')
    setResult(null)
    setError(null)
    setSchemaChecked({})
    setSqlDraft('')
    setCorrectionReason('')
  }

  // 결과가 있으면 그 run이 실제로 실행된 review_config를 쓴다 — 아직 결과가 없는(질의를
  // 입력 중인) 단계에서만 pendingCfg(사용자가 지금 고르고 있는 다음 실행 설정)를 쓴다.
  // 완료된 run에 대해 나중에 토글을 바꿔도 그 run의 실제 검토 이력 표시는 바뀌지 않는다.
  const cfg = result?.review_config ?? pendingCfg
  const stages = computeStages(phase, cfg, result, currentNode)
  const isRunning = isRunningPhase(phase)

  const activeIdx = activeStageIndex(phase, result, currentNode)
  const activeStageNo = phase === 'done' ? '5' : activeIdx >= 0 && activeIdx <= 4 ? String(activeIdx + 1) : null
  const reachedIdx = phase === 'done' ? 4 : activeIdx
  const viewedStageNo = selectedStageNo ?? activeStageNo
  const showSnapshot = !!viewedStageNo && viewedStageNo !== activeStageNo && !!result

  const onSelectStage = (no: string) => {
    setSelectedStageNo(no === activeStageNo ? null : no)
  }

  return {
    phase, result, error, cfg,
    schemaChecked, sqlDraft, setSqlDraft, sqlDraftEdited,
    correctionReason, setCorrectionReason,
    toggleSchemaCandidate: (t: string) => setSchemaChecked((prev) => ({ ...prev, [t]: !prev[t] })),
    goToPhase, loadResult, approveSchema, approveSql, reset,
    stages, isRunning, viewedStageNo, reachedIdx, showSnapshot, onSelectStage,
    currentNode, liveLogs,
  }
}

export type RunReview = ReturnType<typeof useRunReview>
