import { useCallback, useEffect, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import {
  costApi,
  type CostAggregate,
  type DifficultyModelGroup,
  type RecentRun,
  type RunCostDetail,
  type SchemaRagModeGroup,
} from '../../api/costClient'

type Period = 'today' | '7d' | 'all'

const PERIODS: { key: Period; label: string }[] = [
  { key: 'today', label: '오늘' },
  { key: '7d', label: '7일' },
  { key: 'all', label: '전체' },
]

const DIFF_ORDER: Record<string, number> = { easy: 0, medium: 1, hard: 2 }
const DIFF_LABEL: Record<string, string> = { easy: 'easy', medium: 'medium', hard: 'hard' }

const ABLATION_META: Record<string, { tag: string; tagClass: string; label: string }> = {
  full_dump: { tag: 'BEFORE', tagClass: 'before', label: '전체 스키마 덤프' },
  rag: { tag: 'AFTER', tagClass: 'after', label: 'Qdrant 스키마 검색' },
}

function periodToSince(period: Period): string | undefined {
  if (period === 'all') return undefined
  const now = new Date()
  if (period === 'today') {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  }
  return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString()
}

function fmt(n: number): string {
  return n.toLocaleString()
}

interface Props {
  onOpenRunInHistory: (runId: string) => void
}

export function CostDashboard({ onOpenRunInHistory }: Props) {
  const [domain, setDomain] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>('all')

  const [kpi, setKpi] = useState<CostAggregate | null>(null)
  const [ablationGroups, setAblationGroups] = useState<SchemaRagModeGroup[]>([])
  const [routingGroups, setRoutingGroups] = useState<DifficultyModelGroup[]>([])
  const [recentRuns, setRecentRuns] = useState<RecentRun[]>([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [expandedDetail, setExpandedDetail] = useState<RunCostDetail | null>(null)
  const [expandedLoading, setExpandedLoading] = useState(false)

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
          // 스키마 RAG 비교/난이도 라우팅은 오프라인 eval 실행(예: token_cost_comparison.py)까지
          // 포함해야 의미가 있는 비교라 도메인으로 좁히지 않는다 — 실 UI 트래픽만 보는 KPI
          // 스트립·최근 실행 이력과는 성격이 다르다.
          costApi.schemaRagSummary({}),
          costApi.difficultySummary({}),
          costApi.recentRuns({ domain: domainName ?? undefined, limit: 5 }),
          costApi.schemaRagSummary({ domain: domainName ?? undefined }),
        ])
      })
      .then(([ablation, routing, recent, kpiScoped]) => {
        setAblationGroups(ablation.groups)
        setRoutingGroups(routing.groups)
        setRecentRuns(recent.runs)
        setKpi(kpiScoped.overall)
        setPeriod('all')
      })
      .catch((e) => setError(e instanceof Error ? e.message : '비용 집계 조회 실패'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const changePeriod = (p: Period) => {
    setPeriod(p)
    costApi
      .schemaRagSummary({ domain: domain ?? undefined, since: periodToSince(p) })
      .then((res) => setKpi(res.overall))
      .catch(() => {})
  }

  const toggleRun = (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null)
      setExpandedDetail(null)
      return
    }
    setExpandedRunId(runId)
    setExpandedDetail(null)
    setExpandedLoading(true)
    costApi
      .runCost(runId)
      .then(setExpandedDetail)
      .catch(() => setExpandedDetail(null))
      .finally(() => setExpandedLoading(false))
  }

  const isEmpty = !loading && !error && !!kpi && kpi.call_count === 0

  // 실 사용량은 rag 모드만 계속 누적되고 full_dump는 한 차례 eval 실험값에 고정돼 있어
  // (docs/kpi-schema-rag-mode-ablation.md), total_tokens 합계로 비교하면 표본 크기가
  // 갈수록 벌어져 비교가 왜곡된다 — run당 평균 토큰(avg_tokens_per_run)으로 비교해야
  // 호출 횟수와 무관하게 공정하다.
  const before = ablationGroups.find((g) => g.schema_rag_mode === 'full_dump')
  const after = ablationGroups.find((g) => g.schema_rag_mode === 'rag')
  const ablationMax = Math.max(before?.avg_tokens_per_run ?? 0, after?.avg_tokens_per_run ?? 0, 1)
  const reductionPct =
    before && after && before.avg_tokens_per_run > 0
      ? Math.round((1 - after.avg_tokens_per_run / before.avg_tokens_per_run) * 1000) / 10
      : null
  const savedTokensPerRun = before && after ? before.avg_tokens_per_run - after.avg_tokens_per_run : null

  const sortedRouting = [...routingGroups]
    .filter((g) => g.difficulty)
    .sort((a, b) => (DIFF_ORDER[a.difficulty!] ?? 9) - (DIFF_ORDER[b.difficulty!] ?? 9))

  return (
    <>
      <header className="page-header">
        <h1>비용 대시보드</h1>
        <p className="subtitle">스키마 검색과 난이도별 모델 라우팅이 토큰 비용을 어떻게 바꾸는지 확인합니다.</p>
      </header>

      <div className="content">
        {error && (
          <section className="status-section error">
            <div className="status-error">
              <span className="status-error-dot" />
              <div className="status-error-body">
                <span className="status-error-title">비용 집계 조회 실패</span>
                <p className="status-error-msg">{error}</p>
              </div>
              <button className="btn-retry" onClick={loadAll}>
                재시도
              </button>
            </div>
          </section>
        )}

        {!error && loading && (
          <>
            <section className="panel">
              <div className="skeleton-list" style={{ flexDirection: 'row', gap: 40 }}>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                    <div className="skeleton-line" style={{ width: '60%' }} />
                    <div className="skeleton-line" style={{ width: '80%', height: 18 }} />
                  </div>
                ))}
              </div>
            </section>
            <section className="panel">
              <div className="skeleton-list">
                <div className="skeleton-line" style={{ width: 220 }} />
                <div className="skeleton-line" style={{ width: '88%', height: 34 }} />
                <div className="skeleton-line" style={{ width: '52%', height: 34 }} />
              </div>
            </section>
          </>
        )}

        {!error && !loading && isEmpty && (
          <section className="panel">
            <div className="panel-empty">
              아직 실행 기록이 없습니다.
              <br />
              첫 질의를 실행하면 여기 비용이 쌓입니다.
            </div>
          </section>
        )}

        {!error && !loading && !isEmpty && kpi && (
          <>
            {/* Zone A — 요약 스트립 */}
            <section className="panel">
              <div className="cost-strip">
                <div className="cost-strip-item">
                  <span className="cost-strip-label">총 토큰</span>
                  <div className="cost-strip-value">
                    <span>{fmt(kpi.total_tokens)}</span>
                    <span className="unit">tok</span>
                  </div>
                </div>
                <div className="cost-strip-divider" />
                <div className="cost-strip-item">
                  <span className="cost-strip-label">LLM 호출 수</span>
                  <div className="cost-strip-value">
                    <span>{fmt(kpi.call_count)}</span>
                    <span className="unit">calls</span>
                  </div>
                </div>
                <div className="cost-strip-divider" />
                <div className="cost-strip-item">
                  <span className="cost-strip-label">Run당 평균</span>
                  <div className="cost-strip-value">
                    <span>{fmt(kpi.avg_tokens_per_run)}</span>
                    <span className="unit">tok/run</span>
                  </div>
                </div>
                <div className="cost-strip-divider" />
                <div className="cost-strip-item">
                  <span className="cost-strip-label">활성 도메인</span>
                  <span className="cost-strip-value" style={{ fontSize: 13 }}>
                    {domain ?? '-'}
                  </span>
                </div>

                <div className="cost-strip-spacer" />

                <div className="cost-period-group">
                  {PERIODS.map((p) => (
                    <button
                      key={p.key}
                      className={`cost-period-pill ${period === p.key ? 'active' : ''}`}
                      onClick={() => changePeriod(p.key)}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
            </section>

            {/* Zone B — 스키마 검색 도입 전/후 */}
            <section className="panel">
              <div className="panel-head">
                <h2>스키마 검색 도입 전 / 후</h2>
                <span style={{ fontSize: 11.5, color: 'var(--ink-soft)', fontWeight: 400 }}>
                  전체 스키마 덤프 대비 관련 테이블만 주입했을 때의 run당 평균 토큰 사용량
                </span>
                <span className="panel-endpoint">group_by=schema_rag_mode</span>
              </div>

              {!before && !after ? (
                <div className="panel-empty">아직 비교할 데이터가 없습니다.</div>
              ) : (
                <div className="cost-ablation-body" style={{ padding: '16px 20px 20px' }}>
                  <div className="cost-ablation-list">
                    {[before, after].map((g, i) => {
                      if (!g || !g.schema_rag_mode) return null
                      const meta = ABLATION_META[g.schema_rag_mode]
                      if (!meta) return null
                      return (
                        <div className="cost-ablation-row" key={i}>
                          <div className="cost-ablation-top">
                            <span className={`cost-ablation-tag ${meta.tagClass}`}>{meta.tag}</span>
                            <span className="cost-ablation-label">{meta.label}</span>
                            <div style={{ flex: 1 }} />
                            <span className={`cost-ablation-value ${meta.tagClass}`}>{fmt(g.avg_tokens_per_run)}</span>
                            <span style={{ fontSize: 11, color: 'var(--ink-mute)' }}>tok/run</span>
                          </div>
                          <div className="cost-ablation-bar-track">
                            <div
                              className={`cost-ablation-bar-fill ${meta.tagClass}`}
                              style={{ width: `${(g.avg_tokens_per_run / ablationMax) * 100}%` }}
                            />
                          </div>
                          <span className="cost-ablation-meta">
                            {g.call_count} calls · {g.run_count} runs · 총 {fmt(g.total_tokens)} tok
                          </span>
                        </div>
                      )
                    })}
                  </div>

                  {reductionPct !== null && savedTokensPerRun !== null && (
                    <div className={`cost-savings-card ${reductionPct < 0 ? 'negative' : ''}`}>
                      <span className="cost-savings-label">{reductionPct >= 0 ? '토큰 절감' : '토큰 증가'}</span>
                      <div className="cost-savings-value">
                        <span className="arrow">{reductionPct >= 0 ? '▾' : '▴'}</span>
                        <span className="num">{Math.abs(Math.round(reductionPct))}</span>
                        <span className="pct">%</span>
                      </div>
                      <span className="cost-savings-note">
                        run당 {fmt(Math.abs(Math.round(savedTokensPerRun)))} tok
                        <br />
                        {reductionPct >= 0 ? '절감' : '증가'} (실측)
                      </span>
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Zone C — 난이도별 모델 분기 현황 */}
            <section className="panel">
              <div className="panel-head">
                <h2>난이도별 모델 분기 현황</h2>
                <span style={{ fontSize: 11.5, color: 'var(--ink-soft)', fontWeight: 400 }}>
                  난이도 태그가 실제로 어떤 모델을 호출하고 있는지
                </span>
                <span className="panel-endpoint">group_by=difficulty</span>
              </div>

              {sortedRouting.length === 0 ? (
                <div className="panel-empty">아직 난이도별 라우팅 데이터가 없습니다.</div>
              ) : (
                <>
                  <div className="cost-routing-head">
                    <span>난이도</span>
                    <span>라우팅된 모델</span>
                    <span>호출 수</span>
                    <span>총 토큰</span>
                  </div>
                  {sortedRouting.map((g, i) => (
                    <div className="cost-routing-row" key={i}>
                      <span className={`cost-diff-pill ${g.difficulty}`}>{DIFF_LABEL[g.difficulty!] ?? g.difficulty}</span>
                      <span className="cost-model-cell">{g.model}</span>
                      <span className="cost-num-cell">{fmt(g.call_count)}</span>
                      <span className="cost-num-cell strong">{fmt(g.total_tokens)}</span>
                    </div>
                  ))}
                </>
              )}
            </section>

            {/* Zone D — 최근 실행 이력 */}
            <section className="panel">
              <div className="panel-head">
                <h2>최근 실행 이력</h2>
                <span style={{ fontSize: 11.5, color: 'var(--ink-soft)', fontWeight: 400 }}>
                  행을 열면 노드별 호출 내역이 펼쳐집니다
                </span>
                <span className="panel-endpoint">GET /runs/&#123;id&#125;/cost</span>
              </div>

              {recentRuns.length === 0 ? (
                <div className="panel-empty">실행 기록이 없습니다.</div>
              ) : (
                <>
                  <div className="cost-run-head">
                    <span>RUN</span>
                    <span>요약</span>
                    <span>난이도</span>
                    <span>토큰</span>
                    <span />
                  </div>
                  {recentRuns.map((run) => {
                    const isOpen = expandedRunId === run.run_id
                    return (
                      <div className="cost-run-item" key={run.run_id} style={{ background: isOpen ? 'var(--review-bg)' : undefined }}>
                        <div className="cost-run-row" onClick={() => toggleRun(run.run_id)}>
                          <span className="cost-run-id">#{run.run_id.slice(0, 6)}</span>
                          <span className="cost-run-summary">{run.question}</span>
                          {run.difficulty ? (
                            <span className={`cost-diff-pill ${run.difficulty}`}>{DIFF_LABEL[run.difficulty] ?? run.difficulty}</span>
                          ) : (
                            <span className="cost-num-cell">-</span>
                          )}
                          <span className="cost-num-cell strong">{fmt(run.total_tokens)} tok</span>
                          <span className="cost-run-chevron">{isOpen ? '⌄' : '›'}</span>
                        </div>

                        {isOpen && (
                          <div className="cost-run-detail">
                            {expandedLoading && !expandedDetail ? (
                              <div className="panel-empty" style={{ padding: '16px 0' }}>불러오는 중…</div>
                            ) : expandedDetail && expandedDetail.by_node.length > 0 ? (
                              <>
                                <div className="cost-run-detail-head">
                                  <span>NODE</span>
                                  <span>MODEL</span>
                                  <span>CALLS</span>
                                  <span>TOKENS</span>
                                </div>
                                <div className="cost-run-detail-body">
                                  {expandedDetail.by_node.map((n, i) => (
                                    <div className="cost-run-detail-row" key={i}>
                                      <span className="cost-model-cell">{n.node}</span>
                                      <span className="cost-model-cell" style={{ color: 'var(--ink-soft)' }}>{n.model}</span>
                                      <span className="cost-num-cell">{n.calls}</span>
                                      <span className="cost-num-cell strong">{fmt(n.tokens)}</span>
                                    </div>
                                  ))}
                                </div>
                                <div className="cost-run-detail-footer">
                                  <span className="panel-endpoint">GET /runs/{run.run_id}/cost</span>
                                  <div style={{ flex: 1 }} />
                                  <a
                                    href="#"
                                    onClick={(e) => {
                                      e.preventDefault()
                                      onOpenRunInHistory(run.run_id)
                                    }}
                                  >
                                    실행 히스토리에서 전체 보기 →
                                  </a>
                                </div>
                              </>
                            ) : (
                              <div className="panel-empty" style={{ padding: '16px 0' }}>노드별 호출 내역이 없습니다.</div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </>
              )}
            </section>
          </>
        )}
      </div>
    </>
  )
}
