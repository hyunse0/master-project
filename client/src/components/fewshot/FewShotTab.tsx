import { useCallback, useEffect, useMemo, useState } from 'react'
import { domainApi } from '../../api/domainClient'
import { fewshotApi } from '../../api/fewshotClient'
import { FewShotCard } from './FewShotCard'
import { fromCandidate, fromEntry, type FewShotStatus } from './fewShotItem'

const TABS: { key: 'all' | FewShotStatus; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'candidate', label: '후보' },
  { key: 'saved', label: '저장됨' },
  { key: 'synced', label: '반영됨' },
]

interface Props {
  onOpenRun: (runId: string) => void
  // 사이드바 배지는 이 탭을 열지 않아도 보여야 해서 App이 별도로도 조회하지만, 이 탭에서
  // 채택/삭제/반영으로 후보 수가 바뀔 때마다 즉시 갱신되도록 여기서도 올려보낸다.
  onCandidateCountChange?: (count: number) => void
}

export function FewShotTab({ onOpenRun, onCandidateCountChange }: Props) {
  const [domainName, setDomainName] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<ReturnType<typeof fromCandidate>[]>([])
  const [entries, setEntries] = useState<ReturnType<typeof fromEntry>[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [justSynced, setJustSynced] = useState(false)

  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | FewShotStatus>('all')

  useEffect(() => {
    domainApi.status().then((s) => setDomainName(s.domain)).catch(() => setDomainName(null))
  }, [])

  const reload = useCallback((domain: string) => {
    setLoading(true)
    setError(null)
    return Promise.all([fewshotApi.candidates(domain), fewshotApi.entries(domain)])
      .then(([cs, es]) => {
        setCandidates(cs.map(fromCandidate))
        setEntries(es.map(fromEntry))
        onCandidateCountChange?.(cs.length)
      })
      .catch((e) => setError(e instanceof Error ? e.message : '조회 실패'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (domainName) reload(domainName)
  }, [domainName, reload])

  const items = useMemo(() => [...candidates, ...entries], [candidates, entries])

  const counts = useMemo(
    () => ({
      candidate: items.filter((i) => i.status === 'candidate').length,
      saved: items.filter((i) => i.status === 'saved').length,
      synced: items.filter((i) => i.status === 'synced').length,
    }),
    [items],
  )

  const rows = useMemo(() => {
    const query = q.trim()
    return items.filter(
      (i) => (statusFilter === 'all' || i.status === statusFilter) && (!query || i.question.includes(query)),
    )
  }, [items, q, statusFilter])

  const handleAdd = async (runId: string) => {
    if (!domainName) return
    try {
      await fewshotApi.add(domainName, runId)
      await reload(domainName)
    } catch (e) {
      setError(e instanceof Error ? e.message : '추가 실패')
    }
  }

  const handleDelete = async (entryId: string) => {
    if (!domainName) return
    try {
      await fewshotApi.remove(domainName, entryId)
      await reload(domainName)
    } catch (e) {
      setError(e instanceof Error ? e.message : '삭제 실패')
    }
  }

  const handleSync = async () => {
    if (!domainName) return
    setSyncing(true)
    setJustSynced(false)
    try {
      await fewshotApi.seed(domainName)
      await reload(domainName)
      setJustSynced(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '반영 실패')
    } finally {
      setSyncing(false)
    }
  }

  const dirty = !syncing && counts.saved > 0

  return (
    <>
      <header className="page-header">
        <h1>Few-shot 예제 관리</h1>
        <p className="subtitle">사람이 SQL을 고쳐 승인한 실행을 예제로 채택하고, 검색 엔진에 반영합니다.</p>
        <div className="header-spacer" />
        <span className="header-domain-label">domain</span>
        <span className="header-domain-value">{domainName ?? '—'}</span>
      </header>

      <div className="content">
        <section className={`fewshot-banner ${dirty ? 'dirty' : ''}`}>
          <div className="fewshot-banner-stat">
            <span className="fewshot-banner-label">후보</span>
            <span className="fewshot-banner-value">{counts.candidate}건</span>
          </div>
          <span className="fewshot-banner-arrow">→</span>
          <div className="fewshot-banner-stat">
            <span className="fewshot-banner-label">저장됨 (미반영)</span>
            <span className="fewshot-banner-value" style={{ color: counts.saved > 0 ? 'var(--accent)' : undefined }}>
              {counts.saved}건
            </span>
          </div>
          <span className="fewshot-banner-arrow">→</span>
          <div className="fewshot-banner-stat">
            <span className="fewshot-banner-label">반영됨</span>
            <span className="fewshot-banner-value" style={{ color: 'var(--success-text)' }}>{counts.synced}건</span>
          </div>

          <div className="header-spacer" />

          {syncing && (
            <div className="fewshot-sync-status">
              <span className="spinner" />
              <span className="fewshot-sync-label">Qdrant 재구성 중 — {counts.saved + counts.synced}건 색인 중</span>
            </div>
          )}
          {!syncing && dirty && (
            <div className="fewshot-sync-status">
              <span className="fewshot-dirty-note">미반영 {counts.saved}건이 있습니다. 반영하면 파일 내용 전체로 재구성됩니다.</span>
              <button className="btn-primary" onClick={handleSync}>Qdrant에 반영</button>
            </div>
          )}
          {!syncing && !dirty && (
            <div className="fewshot-sync-status">
              <span className="fewshot-clean-note">
                {items.length === 0 ? '아직 채택된 예제가 없습니다.' : `모든 예제가 반영되어 있습니다.${justSynced ? ' 방금 반영' : ''}`}
              </span>
              {items.length > 0 && (
                <button className="btn-secondary" onClick={handleSync}>다시 반영</button>
              )}
            </div>
          )}
        </section>

        {error && <div className="run-error-banner">{error}</div>}

        <section className="fewshot-filter-bar">
          <input
            className="history-search-input"
            style={{ flex: '1 1 260px' }}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="질문 텍스트 검색"
          />
          <div className="fewshot-tabs">
            {TABS.map((t) => (
              <button
                key={t.key}
                className={`fewshot-tab ${statusFilter === t.key ? 'active' : ''}`}
                onClick={() => setStatusFilter(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="header-spacer" />
          <span className="review-section-hint">{rows.length} / {items.length} examples</span>
        </section>

        {!loading && rows.length === 0 && (
          <div className="panel">
            <div className="panel-empty">조건에 맞는 예제가 없습니다.<br />검색어나 필터를 조정해 보세요.</div>
          </div>
        )}

        {rows.length > 0 && (
          <div className="fewshot-list">
            {rows.map((item) => (
              <FewShotCard key={item.key} item={item} onOpenRun={onOpenRun} onAdd={handleAdd} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    </>
  )
}
