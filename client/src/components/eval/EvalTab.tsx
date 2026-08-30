import { useCallback, useEffect, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import {
  evalApi,
  type ExecutionAccuracy,
  type FaithfulnessSummary,
  type SchemaMappingAccuracy,
  type SelfCorrectionSummary,
  type TokenCostComparison,
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

interface TokenComparisonConfig {
  title: string
  experiment: string
  compareKey: string
  beforeTag: string
  afterTag: string
  beforeLabel: string
  afterLabel: string
}

// eval/token_cost_comparison.py를 --experiment 없이 돌리면 f"{key}_ablation"이 기본 실험명이 된다
// (eval/token_cost_comparison.py 참고) — 그 기본값을 그대로 따라간다.
const TOKEN_COMPARISONS: TokenComparisonConfig[] = [
  {
    title: '① 스키마 전체 덤프 vs Qdrant 검색',
    experiment: 'schema_rag_mode_ablation',
    compareKey: 'schema_rag_mode',
    beforeTag: 'full_dump',
    afterTag: 'rag',
    beforeLabel: '전체 스키마 덤프',
    afterLabel: 'Qdrant 스키마 검색',
  },
  {
    title: '② 난이도 라우팅 off vs on',
    experiment: 'routing_mode_ablation',
    compareKey: 'routing_mode',
    beforeTag: 'off',
    afterTag: 'on',
    beforeLabel: '단일 저비용 모델 고정',
    afterLabel: '난이도별 모델 분기',
  },
]

function fmt(n: number): string {
  return n.toLocaleString()
}

function accuracyColor(ratio: number): string {
  if (ratio >= 0.85) return 'var(--success)'
  if (ratio >= 0.7) return 'var(--accent)'
  return '#c99a2e'
}

interface Props {
  onOpenRunInHistory: (runId: string) => void
}

export function EvalTab({ onOpenRunInHistory }: Props) {
  const [domain, setDomain] = useState<string | null>(null)
  const [executionAccuracy, setExecutionAccuracy] = useState<ExecutionAccuracy | null>(null)
  const [schemaMapping, setSchemaMapping] = useState<SchemaMappingAccuracy | null>(null)
  const [faithfulness, setFaithfulness] = useState<FaithfulnessSummary | null>(null)
  const [selfCorrection, setSelfCorrection] = useState<SelfCorrectionSummary | null>(null)
  const [tokenComparisons, setTokenComparisons] = useState<TokenCostComparison[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedFailure, setExpandedFailure] = useState<string | null>(null)

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
          Promise.all(
            TOKEN_COMPARISONS.map((c) =>
              evalApi.tokenCost({ domain: domainName ?? undefined, experiment: c.experiment, compare_key: c.compareKey }),
            ),
          ),
        ])
      })
      .then(([acc, mapping, faith, sc, tokenCosts]) => {
        setExecutionAccuracy(acc)
        setSchemaMapping(mapping)
        setFaithfulness(faith)
        setSelfCorrection(sc)
        setTokenComparisons(tokenCosts)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '평가 지표 조회 실패'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const hasGolden = (executionAccuracy?.overall.total ?? 0) > 0 || (schemaMapping?.overall?.total ?? 0) > 0
  const goldenCaseCount = executionAccuracy?.overall.total ?? schemaMapping?.overall?.total ?? 0
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
                <p className="eval-panel-desc" style={{ maxWidth: 340 }}>
                  {hasGolden
                    ? '정답률과 스키마 매핑 정확도는 이 골든셋을 기준으로 계산됩니다.'
                    : '정답률·스키마 매핑 정확도 섹션은 안내 상태로 표시됩니다. 요약 충실도와 Self-correction 귀인은 골든셋 없이도 집계됩니다.'}
                </p>
              </div>
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
                  SQL은 틀려도 테이블은 제대로 골랐는지를 재는 중간 지표입니다.
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
                <span className="eval-badge">골든셋 불필요</span>
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
                      <div className="eval-faith-head">
                        <span>질문</span>
                        <span>생성된 요약문</span>
                        <span>판정 사유</span>
                        <span />
                      </div>
                      {faithfulness!.failures.map((f) => {
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
                                <div className="eval-faith-detail-footer">
                                  <span className="eval-faith-run-label">run #{f.run_id.slice(0, 6)}</span>
                                  <div style={{ flex: 1 }} />
                                  <a
                                    href="#"
                                    onClick={(e) => {
                                      e.preventDefault()
                                      onOpenRunInHistory(f.run_id)
                                    }}
                                  >
                                    실행 히스토리에서 보기 →
                                  </a>
                                </div>
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

            {/* Self-correction 귀인 */}
            <section className="panel">
              <div className="panel-head">
                <h2>Self-correction 귀인</h2>
                <span className="panel-endpoint">GET /eval/self-correction</span>
              </div>
              <p className="eval-panel-desc" style={{ padding: '0 20px 14px' }}>
                재시도 루프가 어떤 실패 유형에 강한지 보여줍니다.
              </p>

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

            {/* 토큰/비용 비교 */}
            <section className="panel">
              <div className="panel-head">
                <h2>토큰 / 비용 비교</h2>
                <span className="panel-count" style={{ fontWeight: 400 }}>
                  비용 대시보드와 동일한 전/후 비교 카드
                </span>
                <span className="panel-endpoint">GET /eval/token-cost</span>
              </div>

              <div style={{ padding: '4px 20px 20px', display: 'flex', flexDirection: 'column', gap: 22 }}>
                {TOKEN_COMPARISONS.map((cfg, i) => {
                  const groups = tokenComparisons[i]?.groups ?? []
                  const before = groups.find((g) => g.tag_value === cfg.beforeTag)
                  const after = groups.find((g) => g.tag_value === cfg.afterTag)
                  const max = Math.max(before?.total_tokens ?? 0, after?.total_tokens ?? 0, 1)
                  const savePct =
                    before && after && before.total_tokens > 0
                      ? Math.round((1 - after.total_tokens / before.total_tokens) * 100)
                      : null

                  return (
                    <div className="eval-token-block" key={cfg.experiment}>
                      <div className="eval-token-block-head">
                        <span className="title">{cfg.title}</span>
                        <span className="source">experiment={cfg.experiment}</span>
                      </div>

                      {!before && !after ? (
                        <div className="panel-empty">
                          비교 데이터가 없습니다. eval/token_cost_comparison.py --domain {domain ?? '&lt;domain&gt;'} --compare{' '}
                          {cfg.compareKey}={cfg.beforeTag},{cfg.afterTag} --experiment {cfg.experiment} 를 실행하세요.
                        </div>
                      ) : (
                        <div className="eval-token-body">
                          <div className="cost-ablation-list" style={{ flex: '1 1 400px' }}>
                            {[
                              { g: before, tag: 'BEFORE', tagClass: 'before', label: cfg.beforeLabel },
                              { g: after, tag: 'AFTER', tagClass: 'after', label: cfg.afterLabel },
                            ].map(({ g, tag, tagClass, label }) =>
                              g ? (
                                <div className="cost-ablation-row" key={tag}>
                                  <div className="cost-ablation-top">
                                    <span className={`cost-ablation-tag ${tagClass}`}>{tag}</span>
                                    <span className="cost-ablation-label">{label}</span>
                                    <div style={{ flex: 1 }} />
                                    <span className={`cost-ablation-value ${tagClass}`}>{fmt(g.total_tokens)}</span>
                                    <span style={{ fontSize: 11, color: 'var(--ink-mute)' }}>tok</span>
                                  </div>
                                  <div className="cost-ablation-bar-track">
                                    <div
                                      className={`cost-ablation-bar-fill ${tagClass}`}
                                      style={{ width: `${(g.total_tokens / max) * 100}%` }}
                                    />
                                  </div>
                                  <span className="cost-ablation-meta">
                                    {g.calls} calls · {g.runs} runs
                                    {g.success_rate != null ? ` · 성공률 ${Math.round(g.success_rate * 100)}%` : ''}
                                  </span>
                                </div>
                              ) : (
                                <div className="cost-ablation-row" key={tag}>
                                  <span className="cost-ablation-meta">{tag} 데이터 없음</span>
                                </div>
                              ),
                            )}
                          </div>

                          {savePct !== null && (
                            <div className={`cost-savings-card ${savePct < 0 ? 'negative' : ''}`}>
                              <span className="cost-savings-label">{savePct >= 0 ? '토큰 절감' : '토큰 증가'}</span>
                              <div className="cost-savings-value">
                                <span className="arrow">{savePct >= 0 ? '▾' : '▴'}</span>
                                <span className="num">{Math.abs(savePct)}</span>
                                <span className="pct">%</span>
                              </div>
                              <span className="cost-savings-note">
                                {fmt(Math.abs((before?.total_tokens ?? 0) - (after?.total_tokens ?? 0)))} tok
                                <br />
                                {savePct >= 0 ? '절감' : '증가'} (실측)
                              </span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          </>
        )}
      </div>
    </>
  )
}
