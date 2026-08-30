import { useCallback, useEffect, useRef, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import {
  evalApi,
  type ExecutionAccuracy,
  type ExecutionAccuracyJob,
  type FaithfulnessSummary,
  type GoldenSetList,
  type SchemaMappingAccuracy,
  type SelfCorrectionJob,
  type SelfCorrectionSummary,
} from '../../api/evalClient'
import { formatRelativeTime } from '../history/relativeTime'

const DIFF_ORDER: Record<string, number> = { easy: 0, medium: 1, hard: 2 }

const OUTCOME_ORDER = ['first_try_success', 'corrected_by_retry', 'still_failed'] as const
const OUTCOME_META: Record<string, { label: string; color: string }> = {
  first_try_success: { label: '1차 성공', color: 'var(--success)' },
  corrected_by_retry: { label: '재시도로 성공', color: 'var(--accent)' },
  still_failed: { label: '끝내 실패', color: 'var(--danger)' },
}

// execution.py/validation.py/sql_generation이 실제로 내보내는 retry_error_code 값 전부.
const ERROR_CODE_LABEL: Record<string, string> = {
  SCHEMA_CITATION_FAIL: '스키마 인용 오류',
  VALUE_ANCHOR_FAIL: '값 매칭 오류',
  SQL_VALIDATION_FAIL: 'SQL 검증 오류',
  ZERO_ROWS_WITH_VALUE_FILTER: '0건 + 값 필터 재검 실패',
  VALUE_UNCONFIRMED: '값 미확인',
  TIMEOUT: '쿼리 타임아웃',
  UNSAFE_SQL: 'SQL 실행 오류',
}

function accuracyColor(ratio: number): string {
  if (ratio >= 0.85) return 'var(--success)'
  if (ratio >= 0.7) return 'var(--accent)'
  return '#c99a2e'
}

export function EvalTab() {
  const [domain, setDomain] = useState<string | null>(null)
  const [executionAccuracy, setExecutionAccuracy] = useState<ExecutionAccuracy | null>(null)
  const [schemaMapping, setSchemaMapping] = useState<SchemaMappingAccuracy | null>(null)
  const [faithfulness, setFaithfulness] = useState<FaithfulnessSummary | null>(null)
  const [selfCorrection, setSelfCorrection] = useState<SelfCorrectionSummary | null>(null)
  const [goldenSet, setGoldenSet] = useState<GoldenSetList | null>(null)
  const [accuracyJob, setAccuracyJob] = useState<ExecutionAccuracyJob | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)
  const [scJob, setScJob] = useState<SelfCorrectionJob | null>(null)
  const [scRunError, setScRunError] = useState<string | null>(null)
  const scPollRef = useRef<number | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedFailure, setExpandedFailure] = useState<string | null>(null)
  const [expandedGolden, setExpandedGolden] = useState<number | null>(null)
  const [goldenPanelOpen, setGoldenPanelOpen] = useState(false)
  const [faithFailuresOpen, setFaithFailuresOpen] = useState(false)

  const loadAll = useCallback(() => {
    setLoading(true)
    setError(null)
    domainApi
      .status()
      .then((s) => (s.connected ? s.domain : null))
      .catch(() => null)
      .then((domainName) => {
        setDomain(domainName)
        return Promise.all([
          evalApi.executionAccuracy(domainName ?? undefined),
          evalApi.schemaMappingAccuracy(domainName ?? undefined),
          evalApi.faithfulness(domainName ?? undefined),
          evalApi.selfCorrection(domainName ?? undefined),
          evalApi.goldenSet(domainName ?? undefined),
        ])
      })
      .then(([acc, mapping, faith, sc, golden]) => {
        setExecutionAccuracy(acc)
        setSchemaMapping(mapping)
        setFaithfulness(faith)
        setSelfCorrection(sc)
        setGoldenSet(golden)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '평가 지표 조회 실패'))
      .finally(() => setLoading(false))
  }, [])

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const startPolling = useCallback(
    (domainName: string) => {
      if (pollRef.current !== null) return
      pollRef.current = window.setInterval(() => {
        evalApi
          .executionAccuracyStatus(domainName)
          .then(({ job }) => {
            setAccuracyJob(job)
            if (!job || job.status !== 'running') {
              stopPolling()
              if (job?.status === 'done') loadAll()
            }
          })
          .catch(() => stopPolling())
      }, 2000)
    },
    [loadAll, stopPolling],
  )

  useEffect(() => {
    loadAll()
    return () => stopPolling()
  }, [loadAll, stopPolling])

  // 탭을 다시 열었을 때 이미 돌고 있는 job이 있으면(다른 탭/이전 방문에서 시작) 그 진행률에 이어붙는다.
  useEffect(() => {
    if (!domain) return
    evalApi
      .executionAccuracyStatus(domain)
      .then(({ job }) => {
        if (job?.status === 'running') {
          setAccuracyJob(job)
          startPolling(domain)
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain])

  const handleRunAccuracy = useCallback(() => {
    if (!domain) return
    setRunError(null)
    evalApi
      .runExecutionAccuracy(domain)
      .then(({ job }) => {
        setAccuracyJob(job)
        startPolling(domain)
      })
      .catch((e) => setRunError(e instanceof Error ? e.message : '실행 시작 실패'))
  }, [domain, startPolling])

  const stopScPolling = useCallback(() => {
    if (scPollRef.current !== null) {
      window.clearInterval(scPollRef.current)
      scPollRef.current = null
    }
  }, [])

  const startScPolling = useCallback(
    (domainName: string) => {
      if (scPollRef.current !== null) return
      scPollRef.current = window.setInterval(() => {
        evalApi
          .selfCorrectionStatus(domainName)
          .then(({ job }) => {
            setScJob(job)
            if (!job || job.status !== 'running') {
              stopScPolling()
              if (job?.status === 'done') loadAll()
            }
          })
          .catch(() => stopScPolling())
      }, 2000)
    },
    [loadAll, stopScPolling],
  )

  useEffect(() => stopScPolling, [stopScPolling])

  // 탭을 다시 열었을 때 이미 돌고 있는 self-correction job이 있으면 진행률에 이어붙는다.
  useEffect(() => {
    if (!domain) return
    evalApi
      .selfCorrectionStatus(domain)
      .then(({ job }) => {
        if (job?.status === 'running') {
          setScJob(job)
          startScPolling(domain)
        }
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain])

  const handleRunSelfCorrection = useCallback(() => {
    if (!domain) return
    setScRunError(null)
    evalApi
      .runSelfCorrection(domain)
      .then(({ job }) => {
        setScJob(job)
        startScPolling(domain)
      })
      .catch((e) => setScRunError(e instanceof Error ? e.message : '실행 시작 실패'))
  }, [domain, startScPolling])

  const goldenCases = goldenSet?.cases ?? []
  const hasGolden = goldenCases.length > 0
  const goldenCaseCount = goldenCases.length
  const lastRunAt = executionAccuracy?.overall.last_run_at ?? null

  const sortedAccuracy = [...(executionAccuracy?.groups ?? [])]
    .filter((g) => g.difficulty)
    .sort((a, b) => (DIFF_ORDER[a.difficulty!] ?? 9) - (DIFF_ORDER[b.difficulty!] ?? 9))

  const mappingCards = schemaMapping?.overall
    ? [
        { key: 'precision', val: schemaMapping.overall.precision, note: '고른 테이블 중 정답 비율' },
        { key: 'recall', val: schemaMapping.overall.recall, note: '정답 테이블 중 찾은 비율' },
        { key: 'f1', val: schemaMapping.overall.f1, note: '조화 평균', highlight: true },
      ]
    : []

  const faithOverall = faithfulness?.overall
  const faithRatioPct = faithOverall?.ratio != null ? (faithOverall.ratio * 100).toFixed(1) : null

  const scOutcomeCounts = new Map((selfCorrection?.outcomes ?? []).map((o) => [o.outcome, o.count]))
  const scTotal = OUTCOME_ORDER.reduce((sum, key) => sum + (scOutcomeCounts.get(key) ?? 0), 0)
  const scBands = OUTCOME_ORDER.map((key) => ({
    key,
    ...OUTCOME_META[key],
    count: scOutcomeCounts.get(key) ?? 0,
  }))

  const scByCode = new Map<string, { corrected: number; failed: number }>()
  for (const row of selfCorrection?.by_error_code ?? []) {
    if (!row.first_error_code) continue
    const entry = scByCode.get(row.first_error_code) ?? { corrected: 0, failed: 0 }
    if (row.outcome === 'corrected_by_retry') entry.corrected += row.count
    else if (row.outcome === 'still_failed') entry.failed += row.count
    scByCode.set(row.first_error_code, entry)
  }
  const scRows = Array.from(scByCode.entries())
    .map(([code, { corrected, failed }]) => {
      const occurred = corrected + failed
      return {
        code,
        label: ERROR_CODE_LABEL[code] ?? code,
        occurred,
        fixed: corrected,
        ratio: occurred ? corrected / occurred : 0,
      }
    })
    .sort((a, b) => b.occurred - a.occurred)

  return (
    <>
      <header className="page-header">
        <h1>Golden Set 평가</h1>
        <p className="subtitle">에이전트의 정답률, 요약 충실도, 재시도 효과를 지표로 확인합니다.</p>
      </header>

      <div className="content">
        {error && (
          <section className="status-section error">
            <div className="status-error">
              <span className="status-error-dot" />
              <div className="status-error-body">
                <span className="status-error-title">평가 지표 조회 실패</span>
                <p className="status-error-msg">{error}</p>
              </div>
              <button className="btn-retry" onClick={loadAll}>
                재시도
              </button>
            </div>
          </section>
        )}

        {!error && loading && (
          <section className="panel">
            <div className="skeleton-list" style={{ flexDirection: 'row', gap: 40 }}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                  <div className="skeleton-line" style={{ width: '60%' }} />
                  <div className="skeleton-line" style={{ width: '80%', height: 18 }} />
                </div>
              ))}
            </div>
          </section>
        )}

        {!error && !loading && (
          <>
            {/* 상태 스트립 */}
            <section className="status-section">
              <div className="status-connected">
                <div className="status-dot-row">
                  <span className="status-dot" style={{ background: hasGolden ? undefined : '#c99a2e' }} />
                  <span className="status-dot-label" style={{ color: hasGolden ? undefined : 'var(--warn-text)' }}>
                    {hasGolden ? '실측 가능' : '골든셋 없음'}
                  </span>
                </div>
                <div className="status-divider" />
                <div className="status-field">
                  <span className="status-field-label">활성 도메인</span>
                  <span className="status-field-value strong">{domain ?? '-'}</span>
                </div>
                <div className="status-field">
                  <span className="status-field-label">golden_set.json</span>
                  <span className="status-field-value" style={{ color: hasGolden ? undefined : 'var(--warn-text)' }}>
                    {hasGolden ? `${goldenCaseCount} 케이스` : '파일 없음'}
                  </span>
                </div>
                <div className="status-field">
                  <span className="status-field-label">평가 실행 시각</span>
                  <span className="status-field-value">{lastRunAt ? formatRelativeTime(lastRunAt) : '—'}</span>
                </div>
                <div className="status-spacer" />
                <button
                  className="btn-secondary"
                  style={{ padding: '4px 10px', fontSize: 10.5, flexShrink: 0 }}
                  disabled={!domain || !hasGolden || accuracyJob?.status === 'running'}
                  onClick={handleRunAccuracy}
                >
                  {accuracyJob?.status === 'running'
                    ? `실행 중… ${accuracyJob.done}/${accuracyJob.total || goldenCaseCount}`
                    : '지금 실행'}
                </button>
              </div>
              {accuracyJob?.status === 'running' && accuracyJob.last_question && (
                <p className="eval-panel-desc" style={{ marginTop: 10 }}>지금 실행 중: {accuracyJob.last_question}</p>
              )}
              {runError && (
                <p className="eval-panel-desc" style={{ marginTop: 10, color: 'var(--danger-text)' }}>{runError}</p>
              )}
              {accuracyJob?.status === 'error' && (
                <p className="eval-panel-desc" style={{ marginTop: 10, color: 'var(--danger-text)' }}>
                  실행 실패: {accuracyJob.error}
                </p>
              )}
            </section>

            {/* 골든셋 목록 */}
            <section className="panel">
              <div
                className="panel-head"
                style={{ cursor: 'pointer' }}
                onClick={() => setGoldenPanelOpen((v) => !v)}
              >
                <h2>골든셋 목록</h2>
                <span className="panel-count" style={{ fontWeight: 400 }}>
                  {goldenCaseCount}건
                </span>
                <span className="panel-endpoint">GET /eval/golden-set</span>
                <span className="eval-faith-chevron">{goldenPanelOpen ? '⌄' : '›'}</span>
              </div>

              {goldenPanelOpen && (goldenCases.length === 0 ? (
                <div className="panel-empty">
                  golden_set.json이 없습니다.
                  <br />
                  domains/{domain ?? '&lt;domain&gt;'}/golden_set.json을 [{'{'}"question", "expected_sql"{'}'}] 형식으로
                  작성하세요.
                </div>
              ) : (
                <>
                  <div className="eval-faith-head" style={{ gridTemplateColumns: '1fr auto auto' }}>
                    <span>질문</span>
                    <span>마지막 실행</span>
                    <span />
                  </div>
                  {goldenCases.map((c, i) => {
                    const open = expandedGolden === i
                    const last = c.last_run
                    return (
                      <div className="eval-faith-row" key={c.question}>
                        <div
                          className="eval-faith-row-top"
                          style={{ gridTemplateColumns: '1fr auto auto' }}
                          onClick={() => setExpandedGolden(open ? null : i)}
                        >
                          <span className="eval-faith-q">{c.question}</span>
                          {last ? (
                            <span className={`run-status-badge status-${last.ok ? 'success' : 'error'}`}>
                              {last.ok ? 'OK' : 'FAIL'} · {formatRelativeTime(last.created_at)}
                            </span>
                          ) : (
                            <span className="eval-faith-reason">아직 실행 안 함</span>
                          )}
                          <span className="eval-faith-chevron">{open ? '⌄' : '›'}</span>
                        </div>

                        {open && (
                          <div className="eval-faith-detail">
                            <span className="eval-faith-detail-label">정답 SQL (expected_sql)</span>
                            <pre className="sql-view-box" style={{ margin: 0 }}>
                              {c.expected_sql}
                            </pre>

                            {last?.generated_sql && (
                              <>
                                <span className="eval-faith-detail-label">마지막 생성 SQL</span>
                                <pre className="sql-view-box" style={{ margin: 0 }}>
                                  {last.generated_sql}
                                </pre>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </>
              ))}
            </section>

            <div className="eval-grid">
              {/* 난이도별 정답률 */}
              <section className="panel">
                <div className="panel-head">
                  <h2>난이도별 정답률</h2>
                  <span className="panel-count" style={{ fontWeight: 400 }}>
                    Execution Accuracy
                  </span>
                  <span className="panel-endpoint">GET /eval/execution-accuracy</span>
                </div>
                <p className="eval-panel-desc" style={{ padding: '0 20px' }}>
                  생성 SQL을 실행한 결과가 정답 SQL 실행 결과와 일치하면 정답으로 셉니다.
                </p>

                {sortedAccuracy.length === 0 ? (
                  <div className="panel-empty">
                    golden_set.json이 없어 정답률을 계산할 수 없습니다.
                    <br />
                    골든셋이 준비되면 자동으로 표시됩니다.
                  </div>
                ) : (
                  <div className="eval-acc-list">
                    {sortedAccuracy.map((g) => (
                      <div className="eval-acc-row" key={g.difficulty}>
                        <div className="eval-acc-top">
                          <span className={`cost-diff-pill ${g.difficulty}`}>{g.difficulty}</span>
                          <span className="eval-acc-meta">
                            {g.correct} / {g.total} 케이스
                          </span>
                          <div style={{ flex: 1 }} />
                          <span className="eval-acc-pct">{Math.round(g.accuracy * 100)}%</span>
                        </div>
                        <div className="eval-acc-bar-track">
                          <div
                            className="eval-acc-bar-fill"
                            style={{ width: `${g.accuracy * 100}%`, background: accuracyColor(g.accuracy) }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* 스키마 매핑 정확도 */}
              <section className="panel">
                <div className="panel-head">
                  <h2>스키마 매핑 정확도</h2>
                  <span className="panel-endpoint">GET /eval/schema-mapping-accuracy</span>
                </div>
                <p className="eval-panel-desc" style={{ padding: '0 20px' }}>
                  SQL이 틀리더라도 테이블은 제대로 골랐는지를 재는 중간 지표입니다.
                </p>

                {mappingCards.length === 0 ? (
                  <div className="panel-empty">골든셋이 준비되면 자동으로 표시됩니다.</div>
                ) : (
                  <div className="eval-metric-grid">
                    {mappingCards.map((c) => (
                      <div className={`eval-metric-card ${c.highlight ? 'highlight' : ''}`} key={c.key}>
                        <span className="eval-metric-key">{c.key}</span>
                        <span className="eval-metric-val">{c.val != null ? c.val.toFixed(2) : '—'}</span>
                        <span className="eval-metric-note">{c.note}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>

            {/* 요약 충실도 */}
            <section className="panel">
              <div className="panel-head">
                <h2>요약 충실도</h2>
                <span className="panel-count" style={{ fontWeight: 400 }}>
                  Faithfulness
                </span>
                <span className="panel-endpoint">GET /eval/faithfulness</span>
              </div>
              <p className="eval-panel-desc" style={{ padding: '0 20px 14px' }}>
                요약문이 실제 결과에 없는 내용을 지어내지 않았는지를 LLM으로 판정합니다.
              </p>

              {!faithOverall || faithOverall.total === 0 ? (
                <div className="panel-empty">
                  아직 판정 데이터가 없습니다.
                  <br />
                  eval/condition_summary_faithfulness.py를 실행하세요.
                </div>
              ) : (
                <>
                  <div className="eval-faith-top">
                    <div className="eval-faith-pct">
                      <span className="num">{faithRatioPct}</span>
                      <span className="sign">%</span>
                    </div>
                    <div className="eval-faith-labels">
                      <span className="eval-faith-pass">{faithOverall.faithful}건 충실함</span>
                      <span className="eval-faith-fail">
                        {faithOverall.total - faithOverall.faithful}건 판정 실패 · 총 {faithOverall.total}건
                      </span>
                    </div>
                    <div className="eval-faith-bar-track">
                      <div className="eval-faith-bar-fill" style={{ width: `${faithOverall.ratio! * 100}%` }} />
                      <div className="eval-faith-bar-rest" />
                    </div>
                  </div>

                  {(faithfulness?.failures.length ?? 0) === 0 ? (
                    <div className="panel-empty">판정 실패 사례가 없습니다.</div>
                  ) : (
                    <>
                      <div
                        className="eval-faith-head"
                        style={{ cursor: 'pointer' }}
                        onClick={() => setFaithFailuresOpen((v) => !v)}
                      >
                        <span>질문</span>
                        <span>생성된 요약문</span>
                        <span>판정 사유</span>
                        <span className="eval-faith-chevron">{faithFailuresOpen ? '⌄' : '›'}</span>
                      </div>
                      {faithFailuresOpen && faithfulness!.failures.map((f) => {
                        const open = expandedFailure === f.run_id
                        const cols = f.columns ?? []
                        const rows = f.rows ?? []
                        return (
                          <div className="eval-faith-row" key={f.run_id}>
                            <div
                              className="eval-faith-row-top"
                              onClick={() => setExpandedFailure(open ? null : f.run_id)}
                            >
                              <span className="eval-faith-q">{f.question}</span>
                              <span className="eval-faith-summary">{f.summary ?? '—'}</span>
                              <span className="eval-faith-reason">{f.reason ?? '—'}</span>
                              <span className="eval-faith-chevron">{open ? '⌄' : '›'}</span>
                            </div>

                            {open && (
                              <div className="eval-faith-detail">
                                <span className="eval-faith-detail-label">실제 결과 rows</span>
                                {cols.length === 0 ? (
                                  <span style={{ fontSize: 11.5, color: 'var(--ink-mute)' }}>
                                    저장된 결과 미리보기가 없습니다.
                                  </span>
                                ) : (
                                  <div className="eval-faith-detail-table">
                                    <div
                                      className="eval-faith-detail-head"
                                      style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(0,1fr))` }}
                                    >
                                      {cols.map((c) => (
                                        <span key={c}>{c}</span>
                                      ))}
                                    </div>
                                    {rows.map((r, i) => (
                                      <div
                                        className="eval-faith-detail-row"
                                        key={i}
                                        style={{ gridTemplateColumns: `repeat(${cols.length}, minmax(0,1fr))` }}
                                      >
                                        {cols.map((c) => (
                                          <span key={c}>{String(r[c] ?? '')}</span>
                                        ))}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </>
                  )}
                </>
              )}
            </section>

            {/* Self-correction */}
            <section className="panel">
              <div className="panel-head">
                <h2>Self-correction</h2>
                <button
                  className="btn-secondary"
                  style={{ padding: '4px 10px', fontSize: 10.5, flexShrink: 0 }}
                  disabled={!domain || scJob?.status === 'running'}
                  onClick={handleRunSelfCorrection}
                >
                  {scJob?.status === 'running' ? `실행 중… ${scJob.done}/${scJob.total || '?'}` : '지금 실행'}
                </button>
                <span className="panel-endpoint">GET /eval/self-correction</span>
              </div>
              <p className="eval-panel-desc" style={{ padding: '0 20px 14px' }}>
                재시도 루프가 어떤 실패 유형에 강한지 보여줍니다.
                {scJob?.status === 'running' && scJob.last_question && (
                  <>
                    <br />
                    지금 실행 중: {scJob.last_question}
                  </>
                )}
              </p>
              {scRunError && (
                <p className="eval-panel-desc" style={{ padding: '0 20px 14px', color: 'var(--danger-text)' }}>
                  {scRunError}
                </p>
              )}
              {scJob?.status === 'error' && (
                <p className="eval-panel-desc" style={{ padding: '0 20px 14px', color: 'var(--danger-text)' }}>
                  실행 실패: {scJob.error}
                </p>
              )}

              {scTotal === 0 ? (
                <div className="panel-empty">
                  아직 데이터가 없습니다.
                  <br />
                  eval/self_correction_ablation.py를 실행하세요.
                </div>
              ) : (
                <div style={{ padding: '0 20px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <div className="eval-sc-bands">
                    {scBands.map((b) => (
                      <div
                        className="eval-sc-band"
                        key={b.key}
                        style={{ width: `${(b.count / scTotal) * 100}%`, background: b.color }}
                      />
                    ))}
                  </div>
                  <div className="eval-sc-legend">
                    {scBands.map((b) => (
                      <div className="eval-sc-legend-item" key={b.key}>
                        <span className="eval-sc-legend-dot" style={{ background: b.color }} />
                        <span className="eval-sc-legend-label">{b.label}</span>
                        <span className="eval-sc-legend-val">
                          {b.count}건 ({Math.round((b.count / scTotal) * 100)}%)
                        </span>
                      </div>
                    ))}
                  </div>

                  {scRows.length > 0 && (
                    <>
                      <div className="eval-sc-head" style={{ marginTop: 6 }}>
                        <span>실패 유형</span>
                        <span>발생</span>
                        <span>재시도 성공</span>
                        <span>교정률</span>
                      </div>
                      {scRows.map((r) => (
                        <div className="eval-sc-row" key={r.code}>
                          <span className="eval-sc-type">{r.label}</span>
                          <span className="eval-sc-num">{r.occurred}건</span>
                          <span className="eval-sc-num">{r.fixed}건</span>
                          <div className="eval-sc-pct-cell">
                            <div className="eval-sc-pct-track">
                              <div
                                className="eval-sc-pct-fill"
                                style={{
                                  width: `${r.ratio * 100}%`,
                                  background: r.ratio >= 0.75 ? 'var(--success)' : r.ratio >= 0.5 ? 'var(--accent)' : '#c99a2e',
                                }}
                              />
                            </div>
                            <span
                              className="eval-sc-pct-val"
                              style={{ color: r.ratio >= 0.75 ? 'var(--success-text)' : '#2c3238' }}
                            >
                              {Math.round(r.ratio * 100)}%
                            </span>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </>
  )
}
