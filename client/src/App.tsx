import { useCallback, useEffect, useState } from 'react'
import { domainApi, type DomainStatus, type TableSummary, type TableDetail } from './api/domainClient'
import { QueryRunTab } from './components/queryRun/QueryRunTab'
import './App.css'

type Phase = 'loading' | 'connected' | 'error'
type View = 'query' | 'domain'

const NAV_GROUPS: { label: string; items: { label: string; view?: View; soon: boolean }[] }[] = [
  {
    label: '에이전트',
    items: [
      { label: '질의 실행', view: 'query', soon: false },
      { label: '실행 히스토리', soon: true },
    ],
  },
  {
    label: '에이전트 관리',
    items: [
      { label: '도메인 관리', view: 'domain', soon: false },
      { label: '검토 정책', soon: true },
      { label: 'Golden Set 평가', soon: true },
      { label: '비용 대시보드', soon: true },
    ],
  },
]

function Sidebar({ current, onSelect }: { current: View; onSelect: (view: View) => void }) {
  return (
    <aside className="rail">
      <div className="rail-brand">
        <span className="rail-mark">NL</span>
        <span className="rail-title">NL2SQL 에이전트</span>
      </div>
      <nav className="rail-nav">
        {NAV_GROUPS.map((group, i) => (
          <div key={group.label}>
            {i > 0 && <div className="rail-divider" />}
            <div className="rail-group-label">{group.label}</div>
            {group.items.map((item) => (
              <div
                key={item.label}
                className={`rail-link ${item.view === current ? 'current' : ''}`}
                onClick={item.view ? () => onSelect(item.view!) : undefined}
                style={item.view ? { cursor: 'pointer' } : undefined}
              >
                <span className="rail-dot" />
                <span className="rail-label">{item.label}</span>
                {item.soon && <span className="rail-soon">SOON</span>}
              </div>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  )
}

function StatusSection({
  phase,
  status,
  errorMessage,
  onRetry,
}: {
  phase: Phase
  status: DomainStatus | null
  errorMessage: string | null
  onRetry: () => void
}) {
  if (phase === 'loading') {
    return (
      <section className="status-section">
        <div className="status-loading">
          <span className="spinner" />
          <span className="status-loading-text">도메인 접속 상태 확인 중…</span>
          <span className="status-endpoint">GET /domain/status</span>
        </div>
      </section>
    )
  }

  if (phase === 'error') {
    return (
      <section className="status-section error">
        <div className="status-error">
          <span className="status-error-dot" />
          <div className="status-error-body">
            <div className="status-error-head">
              <span className="status-error-title">연결 실패</span>
              {status && (
                <span className="status-error-dsn">
                  {status.domain} · {status.host}:{status.port}/{status.dbname}
                </span>
              )}
            </div>
            <p className="status-error-msg">{errorMessage ?? '알 수 없는 오류가 발생했습니다.'}</p>
          </div>
          <button className="btn-retry" onClick={onRetry}>
            재시도
          </button>
        </div>
      </section>
    )
  }

  if (!status) return null

  return (
    <section className="status-section">
      <div className="status-connected">
        <div className="status-dot-row">
          <span className="status-dot" />
          <span className="status-dot-label">연결됨</span>
        </div>
        <div className="status-divider" />
        <div className="status-field">
          <span className="status-field-label">DOMAIN</span>
          <span className="status-field-value strong">{status.domain}</span>
        </div>
        <div className="status-field">
          <span className="status-field-label">HOST</span>
          <span className="status-field-value">
            {status.host}:{status.port} / {status.dbname}
          </span>
        </div>
        <div className="status-field">
          <span className="status-field-label">SCHEMAS</span>
          <span className="status-field-value">{status.schemas.join(', ')}</span>
        </div>
        <div className="status-spacer" />
        <span className="status-endpoint">GET /domain/status</span>
      </div>
    </section>
  )
}

function TableListPanel({
  phase,
  tables,
  tablesLoading,
  selected,
  onSelect,
}: {
  phase: Phase
  tables: TableSummary[]
  tablesLoading: boolean
  selected: string | null
  onSelect: (table: string) => void
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>테이블 목록</h2>
        {phase === 'connected' && !tablesLoading && (
          <span className="panel-count">{tables.length} tables</span>
        )}
        <span className="panel-endpoint">/domain/tables</span>
      </div>

      {phase === 'error' && (
        <div className="panel-empty">
          연결이 끊겨 목록을 불러올 수 없습니다.
          <br />
          상단에서 접속 상태를 먼저 확인하세요.
        </div>
      )}

      {phase === 'connected' && tablesLoading && (
        <div className="skeleton-list">
          <div className="skeleton-line" style={{ width: '70%' }} />
          <div className="skeleton-line" style={{ width: '54%', animationDelay: '.15s' }} />
          <div className="skeleton-line" style={{ width: '78%', animationDelay: '.3s' }} />
          <div className="skeleton-line" style={{ width: '44%', animationDelay: '.45s' }} />
        </div>
      )}

      {phase === 'connected' && !tablesLoading && tables.length === 0 && (
        <div className="panel-empty">대상 스키마에 조회 가능한 테이블이 없습니다.</div>
      )}

      {phase === 'connected' && !tablesLoading && tables.length > 0 && (
        <div className="table-list">
          {tables.map((t) => (
            <button
              key={t.table}
              className={`table-row ${selected === t.table ? 'selected' : ''}`}
              onClick={() => onSelect(t.table)}
            >
              <div className="table-row-top">
                <span className="table-row-name">{t.table}</span>
                <span className="table-row-cols">{t.column_count}</span>
              </div>
              <span className={`table-row-comment ${t.comment ? '' : 'empty'}`}>
                {t.comment ?? '코멘트 없음'}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

function TableDetailPanel({ detail, loading }: { detail: TableDetail | null; loading: boolean }) {
  const schema = detail ? detail.table.split('.').slice(0, -1).join('.') || 'public' : ''

  return (
    <section className="panel panel-detail">
      <div className="panel-head">
        <h2>테이블 상세</h2>
        <span className="panel-endpoint">/domain/tables/{'{table}'}</span>
      </div>

      {loading && <div className="detail-loading">불러오는 중…</div>}

      {!loading && !detail && (
        <div className="panel-placeholder">왼쪽 목록에서 테이블을 선택하세요.</div>
      )}

      {!loading && detail && (
        <div className="detail-body">
          <div className="detail-head">
            <div className="detail-head-main">
              <div className="detail-name-row">
                <span className="detail-name">{detail.table}</span>
                <span className="detail-schema-badge">{schema.toUpperCase()}</span>
              </div>
              <span className="detail-comment">{detail.comment ?? '코멘트 없음'}</span>
            </div>
            <div className="detail-stats">
              <div className="detail-stat">
                <span className="detail-stat-value">{detail.columns.length}</span>
                <span className="detail-stat-label">COLUMNS</span>
              </div>
              <div className="detail-stat">
                <span className="detail-stat-value">{detail.foreign_keys.length}</span>
                <span className="detail-stat-label">FK</span>
              </div>
            </div>
          </div>

          <div className="col-table">
            <div className="col-table-head">
              <span>COLUMN</span>
              <span>TYPE</span>
              <span>COMMENT</span>
            </div>
            {detail.columns.map((c) => (
              <div className="col-table-row" key={c.name}>
                <span className="col-name-cell">
                  <span className="col-name">{c.name}</span>
                  {c.is_primary_key && <span className="pk-badge">PK</span>}
                </span>
                <span className="col-type">{c.type}</span>
                <span className={`col-comment ${c.comment ? '' : 'empty'}`}>
                  {c.comment ?? '코멘트 없음'}
                </span>
              </div>
            ))}
            <div className="col-table-footer">전체 {detail.columns.length}개 컬럼</div>
          </div>

          {detail.foreign_keys.length > 0 && (
            <div className="fk-block">
              <h3 className="fk-title">FOREIGN KEYS</h3>
              <div className="fk-list">
                {detail.foreign_keys.map((fk) => (
                  <div className="fk-row" key={fk.column}>
                    <span className="fk-col">{fk.column}</span>
                    <span className="fk-arrow">→</span>
                    <span className="fk-ref">
                      {fk.ref_table}.{fk.ref_column}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function App() {
  const [view, setView] = useState<View>('query')
  const [phase, setPhase] = useState<Phase>('loading')
  const [status, setStatus] = useState<DomainStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)

  const [tables, setTables] = useState<TableSummary[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)

  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [detail, setDetail] = useState<TableDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadStatus = useCallback(() => {
    setPhase('loading')
    setStatusError(null)
    domainApi
      .status()
      .then((data) => {
        setStatus(data)
        if (data.connected) {
          setPhase('connected')
        } else {
          setStatusError(data.error ?? '알 수 없는 오류가 발생했습니다.')
          setPhase('error')
        }
      })
      .catch((e) => {
        setStatus(null)
        setStatusError(e instanceof Error ? e.message : '상태 조회 실패')
        setPhase('error')
      })
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  useEffect(() => {
    if (phase !== 'connected') return
    setTablesLoading(true)
    domainApi
      .tables()
      .then(setTables)
      .catch(() => setTables([]))
      .finally(() => setTablesLoading(false))
  }, [phase])

  const selectTable = (table: string) => {
    setSelectedTable(table)
    setDetailLoading(true)
    domainApi
      .tableDetail(table)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  return (
    <div className="shell">
      <Sidebar current={view} onSelect={setView} />
      <main className="main">
        {view === 'query' ? (
          <QueryRunTab />
        ) : (
          <>
            <header className="page-header">
              <h1>도메인 관리</h1>
              <p className="subtitle">연결된 DB의 테이블과 컬럼 메타데이터를 확인합니다.</p>
            </header>

            <div className="content">
              <StatusSection phase={phase} status={status} errorMessage={statusError} onRetry={loadStatus} />

              <div className="explorer-grid">
                <TableListPanel
                  phase={phase}
                  tables={tables}
                  tablesLoading={tablesLoading}
                  selected={selectedTable}
                  onSelect={selectTable}
                />
                <TableDetailPanel detail={detail} loading={detailLoading} />
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export default App
