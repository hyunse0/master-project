import { useState } from 'react'
import { fewshotApi } from '../../api/fewshotClient'
import type { RunResult } from '../../types'
import { isChartable, ResultChart } from './ResultChart'

function extractSummaryText(markdown: string | null): string {
  if (!markdown) return ''
  const match = markdown.match(/##\s*요약\s*\n([\s\S]*?)(\n##|\s*$)/)
  return match ? match[1].trim() : markdown.trim()
}

// CSV 필드 안에 쉼표/따옴표/줄바꿈이 있으면 RFC 4180대로 큰따옴표로 감싸고 내부 따옴표는 2개로.
function csvField(value: unknown): string {
  const s = String(value ?? '')
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function downloadCsv(columns: string[], rows: Record<string, unknown>[], filename: string): void {
  const lines = [
    columns.map(csvField).join(','),
    ...rows.map((row) => columns.map((c) => csvField(row[c])).join(',')),
  ]
  // 엑셀에서 한글이 깨지지 않도록 UTF-8 BOM을 붙인다.
  const blob = new Blob(['﻿', lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

type FewShotAddState = 'idle' | 'saving' | 'added' | 'exists' | 'error'

export function ResultCard({ result }: { result: RunResult }) {
  const columns = result.columns
  const rows = result.rows
  const displayCount = Math.min(20, rows.length)
  const [fewShotState, setFewShotState] = useState<FewShotAddState>('idle')

  const handleExportCsv = () => {
    downloadCsv(columns, rows, `result_${result.run_id.slice(0, 8)}.csv`)
  }

  // Golden Set은 정답률 평가(Golden Set 평가 탭)에만 쓰이고 실제 에이전트에는 반영되지 않는다
  // — 지금 이 결과를 다음 질문부터 실제로 참고하게 하려면 few_shot.json에 채택해 Qdrant에
  // 재임베딩(Few-shot 예제 관리 탭의 "Qdrant에 반영")해야 한다.
  const handleAddToFewShot = async () => {
    if (!result.sql) return
    setFewShotState('saving')
    try {
      const r = await fewshotApi.add(result.domain, result.run_id)
      setFewShotState(r.status)
    } catch {
      setFewShotState('error')
    }
  }

  const fewShotLabel: Record<FewShotAddState, string> = {
    idle: 'Few-shot에 추가',
    saving: '추가 중…',
    added: '추가됨',
    exists: '이미 있음',
    error: '추가 실패 — 다시 시도',
  }

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
          <button className="btn-secondary" onClick={handleExportCsv} disabled={rows.length === 0}>
            CSV 내보내기
          </button>
          <button
            className="btn-secondary"
            onClick={handleAddToFewShot}
            disabled={!result.sql || fewShotState === 'saving' || fewShotState === 'added' || fewShotState === 'exists'}
          >
            {fewShotLabel[fewShotState]}
          </button>
        </div>
      </div>
    </section>
  )
}
