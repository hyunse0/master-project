import { useCallback, useEffect, useMemo, useState } from 'react'
import { runsApi } from '../../api/runsClient'
import type { RunSummary } from '../../types'
import { RunDetailPanel } from './RunDetailPanel'
import { RunListPanel } from './RunListPanel'

const PAGE_SIZE = 20

interface Props {
  // 다른 탭(Few-shot 예제 관리 등)에서 특정 run을 바로 보여달라고 넘어올 때만 쓰인다.
  initialSelectedRunId?: string | null
  onConsumedInitialRun?: () => void
}

export function HistoryTab({ initialSelectedRunId = null, onConsumedInitialRun }: Props) {
  const [q, setQ] = useState('')
  const [domainFilter, setDomainFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedRunId)

  // initialSelectedRunId는 마운트 시 seed 값으로만 쓰고, 다 쓰고 나면 부모 상태를 바로
  // 비워달라고 알려준다 — 안 그러면 나중에 사이드바로 히스토리에 다시 들어갈 때도 이
  // run이 계속 재선택돼버린다.
  useEffect(() => {
    if (initialSelectedRunId) onConsumedInitialRun?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchPage = useCallback(
    (before?: string) => {
      setLoading(true)
      return runsApi
        .list({
          domain: domainFilter || undefined,
          status: statusFilter || undefined,
          q: q || undefined,
          limit: PAGE_SIZE,
          before,
        })
        .then((res) => {
          setRuns((prev) => (before ? [...prev, ...res.runs] : res.runs))
          setHasMore(res.has_more)
        })
        .catch(() => {
          if (!before) setRuns([])
          setHasMore(false)
        })
        .finally(() => setLoading(false))
    },
    [domainFilter, statusFilter, q],
  )

  // 검색어는 타이핑마다 요청을 쏘지 않도록 살짝 디바운스한다. 도메인/상태 필터는 select
  // 토글이라 이 정도 디바운스가 없어도 요청 폭주가 안 생겨 그대로 즉시 반영해도 된다.
  useEffect(() => {
    const t = setTimeout(fetchPage, q ? 300 : 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchPage, q])

  // 서버에 "전체 도메인 목록" API가 따로 없어(도메인은 실행 시점마다 바뀔 수 있는 값이라
  // 별도 레지스트리 조회가 필요) 지금까지 불러온 run들에 실제로 등장한 도메인만 후보로 쓴다.
  const domainOptions = useMemo(() => Array.from(new Set(runs.map((r) => r.domain))).sort(), [runs])

  const selected = runs.find((r) => r.run_id === selectedId) ?? null

  return (
    <>
      <header className="page-header">
        <h1>실행 히스토리</h1>
        <p className="subtitle">지난 실행을 다시 보고, 검토 대기 중인 실행은 여기서 이어서 처리합니다.</p>
        <div className="header-spacer" />
        <span className="panel-endpoint">GET /runs</span>
      </header>

      <div className="content history-content">
        <div className="history-grid">
          <RunListPanel
            runs={runs}
            loading={loading}
            hasMore={hasMore}
            onLoadMore={() => runs.length > 0 && fetchPage(runs[runs.length - 1].created_at)}
            q={q}
            onQChange={setQ}
            domainFilter={domainFilter}
            onDomainChange={setDomainFilter}
            domainOptions={domainOptions}
            statusFilter={statusFilter}
            onStatusChange={setStatusFilter}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <RunDetailPanel
            runId={selectedId}
            createdAt={selected?.created_at ?? null}
            onAfterResume={() => fetchPage()}
            onClose={() => setSelectedId(null)}
          />
        </div>
      </div>
    </>
  )
}
