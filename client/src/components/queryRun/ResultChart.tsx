// 집계형(aggregate) 결과 중 "카테고리 1열 + 숫자 1열" 형태일 때만 표 위에 얹는 최소 막대 차트.
// 실제 쿼리 결과 데이터를 그대로 시각화하는 것뿐 — 별도 라이브러리 없이 SVG로 직접 그린다.

const MAX_BARS = 15
const CHART_WIDTH = 480
const BAR_HEIGHT = 16
const BAR_GAP = 5
const LABEL_WIDTH = 140

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

export function isChartable(
  columns: string[],
  rows: Record<string, unknown>[],
  queryType: 'aggregate' | 'list' | 'cohort' | null,
): boolean {
  if (queryType !== 'aggregate') return false
  if (columns.length !== 2) return false
  if (rows.length < 1 || rows.length > MAX_BARS) return false
  const valueCol = columns[1]
  return rows.every((row) => toFiniteNumber(row[valueCol]) !== null)
}

export function ResultChart({
  columns,
  rows,
}: {
  columns: string[]
  rows: Record<string, unknown>[]
}) {
  const [categoryCol, valueCol] = columns
  const values = rows.map((row) => toFiniteNumber(row[valueCol]) ?? 0)
  const max = Math.max(...values, 1)
  const plotWidth = CHART_WIDTH - LABEL_WIDTH
  const height = rows.length * (BAR_HEIGHT + BAR_GAP)

  return (
    <div className="result-block">
      <span className="review-section-label">CHART</span>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${height}`}
        width="100%"
        role="img"
        aria-label={`${categoryCol}별 ${valueCol} 막대 차트`}
        style={{ display: 'block', marginTop: 8, maxWidth: CHART_WIDTH }}
      >
        {rows.map((row, i) => {
          const value = values[i]
          const barWidth = (value / max) * plotWidth
          const y = i * (BAR_HEIGHT + BAR_GAP)
          return (
            <g key={i}>
              <text
                x={LABEL_WIDTH - 8}
                y={y + BAR_HEIGHT / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize="12"
                fill="var(--ink-soft)"
              >
                {String(row[categoryCol] ?? '')}
              </text>
              <rect
                x={LABEL_WIDTH}
                y={y}
                width={Math.max(barWidth, 2)}
                height={BAR_HEIGHT}
                rx={3}
                fill="var(--accent)"
              />
              <text
                x={LABEL_WIDTH + Math.max(barWidth, 2) + 6}
                y={y + BAR_HEIGHT / 2}
                dominantBaseline="middle"
                fontSize="12"
                fill="var(--ink)"
              >
                {value}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
