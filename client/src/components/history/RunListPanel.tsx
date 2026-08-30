import type { RunSummary } from '../../types'
import { formatDuration, formatRelativeTime } from './relativeTime'
import { STATUS_CLASS, STATUS_LABEL, STATUS_OPTIONS } from './runStatus'

interface Props {
  runs: RunSummary[]
  loading: boolean
  hasMore: boolean
  onLoadMore: () => void
  q: string
  onQChange: (q: string) => void
  domainFilter: string
  onDomainChange: (domain: string) => void
  domainOptions: string[]
  statusFilter: string
  onStatusChange: (status: string) => void
  selectedId: string | null
  onSelect: (runId: string) => void
}

export function RunListPanel({
  runs, loading, hasMore, onLoadMore,
  q, onQChange, domainFilter, onDomainChange, domainOptions,
  statusFilter, onStatusChange,
  selectedId, onSelect,
}: Props) {
  return (
    <section className="panel history-list-panel">
      <div className="history-list-head">
        <div className="history-list-head-row">
          <h2>Run 목록</h2>
          <span className="panel-count">{runs.length}건{hasMore ? '+' : ''}</span>
          <div className="header-spacer" />
          <span className="panel-endpoint">최신순 · GET /runs</span>
        </div>

        <input
          className="history-search-input"
          value={q}
          onChange={(e) => onQChange(e.target.value)}
          placeholder="질문 텍스트 검색"
        />

        <div className="history-filter-row">
          <select value={domainFilter} onChange={(e) => onDomainChange(e.target.value)}>
            <option value="">도메인 · 전체</option>
            {domainOptions.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <select value={statusFilter} onChange={(e) => onStatusChange(e.target.value)}>
            <option value="">상태 · 전체</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      {!loading && runs.length === 0 && (
        <div className="panel-empty">
          조건에 맞는 실행 기록이 없습니다.
          <br />
          검색어나 필터를 조정해 보세요.
        </div>
      )}

      {loading && runs.length === 0 && (
        <div className="skeleton-list">
          <div className="skeleton-line" style={{ width: '70%' }} />
          <div className="skeleton-line" style={{ width: '54%', animationDelay: '.15s' }} />
          <div className="skeleton-line" style={{ width: '78%', animationDelay: '.3s' }} />
        </div>
      )}

      {runs.length > 0 && (
        <div className="history-list">
          {runs.map((r) => (
            <button
              key={r.run_id}
              className={`history-row ${r.run_id === selectedId ? 'selected' : ''}`}
              onClick={() => onSelect(r.run_id)}
            >
              <div className="history-row-top">
                <span className={`history-status-dot ${STATUS_CLASS[r.status]}`} />
                <span className={`run-status-badge ${STATUS_CLASS[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                <div className="header-spacer" />
                <span className="history-row-id">{r.run_id.slice(0, 8)}</span>
              </div>
              <span className="history-row-question">{r.question}</span>
              <div className="history-row-meta">
                <span>{formatRelativeTime(r.created_at)}</span>
                <span className="history-row-dot">·</span>
                <span>{formatDuration(r.latency_ms)}</span>
                <div className="header-spacer" />
                <span className="history-row-domain">{r.domain}</span>
              </div>
            </button>
          ))}
          {hasMore && (
            <div className="history-load-more">
              <button className="btn-secondary" onClick={onLoadMore} disabled={loading}>
                {loading ? '불러오는 중…' : '더보기'}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
