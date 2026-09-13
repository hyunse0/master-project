import type { RunResult } from '../../types'
import { isChartable, ResultChart } from './ResultChart'

function extractSummaryText(markdown: string | null): string {
  if (!markdown) return ''
  const match = markdown.match(/##\s*요약\s*\n([\s\S]*?)(\n##|\s*$)/)
  return match ? match[1].trim() : markdown.trim()
}

export function ResultCard({ result }: { result: RunResult }) {
  const columns = result.columns
  const rows = result.rows
  const displayCount = Math.min(20, rows.length)

  return (
    <section className="result-card">
      <div className="result-card-head">
        <span className="result-dot" />
        <h2 className="result-card-title">실행 결과</h2>
        <span className="result-card-meta">
          {result.row_count ?? 0}행 · {(result.latency_ms / 1000).toFixed(1)}s
        </span>
        <div className="review-card-spacer" />
        <span className="review-endpoint-label">GET /runs/{result.run_id}/trace</span>
      </div>

      <div className="result-card-body">
        <div className="result-block">
          <span className="review-section-label">SUMMARY</span>
          <p className="result-summary-text">{extractSummaryText(result.summary)}</p>
        </div>

        <div className="result-block">
          <div className="sql-review-label-row">
            <span className="review-section-label">EXECUTED SQL</span>
            {result.sql_edited && <span className="sql-edited-badge">사용자 수정 반영됨</span>}
          </div>
          <pre className="sql-view-box">{result.sql}</pre>
        </div>

        {isChartable(columns, rows, result.query_type) && (
          <ResultChart columns={columns} rows={rows} />
        )}

        {columns.length > 0 && (
          <div className="result-block">
            <div className="sql-review-label-row">
              <span className="review-section-label">RESULT</span>
              <span className="review-section-hint">
                상위 {displayCount}행 / {rows.length}행
              </span>
            </div>
            <div className="result-table-wrap">
              <div className="result-table-head" style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr)` }}>
                {columns.map((c) => (
                  <span key={c}>{c}</span>
                ))}
              </div>
              {rows.slice(0, displayCount).map((row, i) => (
                <div
                  key={i}
                  className="result-table-row"
                  style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr)` }}
                >
                  {columns.map((c) => (
                    <span key={c}>{String(row[c] ?? '')}</span>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="result-card-footer">
          <button className="btn-secondary" disabled title="구현 예정">
            CSV 내보내기
          </button>
          <button className="btn-secondary" disabled title="구현 예정">
            Golden Set에 추가
          </button>
        </div>
      </div>
    </section>
  )
}
