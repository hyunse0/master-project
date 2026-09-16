import { useEffect, useMemo, useState } from 'react'
import {
  domainApi,
  type CodesetData,
  type DomainNote,
  type DomainNoteCategory,
  type JoinData,
  type TableColumn,
  type TableSummary,
} from '../../api/domainClient'

const GENERAL_OPTION = '__general__'

const CATEGORY_LABEL: Record<DomainNoteCategory, string> = {
  codeset: '코드셋',
  join: '조인',
  general: '일반',
}

function parseCodes(text: string): Record<string, string> {
  const codes: Record<string, string> = {}
  for (const part of text.split(',')) {
    const idx = part.indexOf('=')
    if (idx <= 0) continue
    const code = part.slice(0, idx).trim()
    const meaning = part.slice(idx + 1).trim()
    if (code && meaning) codes[code] = meaning
  }
  return codes
}

function codesToText(codes: Record<string, string>): string {
  return Object.entries(codes).map(([k, v]) => `${k}=${v}`).join(', ')
}

function renderCodesetNote(data: CodesetData): string {
  const codesText = codesToText(data.codes)
  let text = `${data.table}.${data.column} 코드값: ${codesText}.`
  if (data.remark) text += ` ${data.remark}`
  return text
}

function renderJoinNote(data: JoinData): string {
  let text = `${data.tables[0]}.${data.columns[0]} = ${data.tables[1]}.${data.columns[1]}로 JOIN한다.`
  if (data.remark) text += ` ${data.remark}`
  return text
}

interface Props {
  tables: TableSummary[]
  onClose: () => void
}

export function DomainNotesModal({ tables, onClose }: Props) {
  const [notes, setNotes] = useState<DomainNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // 상단 등록/수정 폼 — codeset/join은 필드가 여러 개라 행 내 인라인 편집 대신 이 폼을 재사용한다.
  const [formCategory, setFormCategory] = useState<DomainNoteCategory>('codeset')
  const [editingId, setEditingId] = useState<string | null>(null)

  const [generalTable, setGeneralTable] = useState(GENERAL_OPTION)
  const [generalText, setGeneralText] = useState('')

  const [csTable, setCsTable] = useState('')
  const [csColumn, setCsColumn] = useState('')
  const [csColumns, setCsColumns] = useState<TableColumn[]>([])
  const [csCodesText, setCsCodesText] = useState('')
  const [csRemark, setCsRemark] = useState('')

  const [joinTableA, setJoinTableA] = useState('')
  const [joinTableB, setJoinTableB] = useState('')
  const [joinColumnsA, setJoinColumnsA] = useState<TableColumn[]>([])
  const [joinColumnsB, setJoinColumnsB] = useState<TableColumn[]>([])
  const [joinColumnA, setJoinColumnA] = useState('')
  const [joinColumnB, setJoinColumnB] = useState('')
  const [joinRemark, setJoinRemark] = useState('')

  // 테이블 선택 시 해당 테이블의 컬럼 목록을 가져와 컬럼 드롭다운을 채운다.
  useEffect(() => {
    if (!csTable) { setCsColumns([]); return }
    domainApi.tableDetail(csTable).then((d) => setCsColumns(d.columns)).catch(() => setCsColumns([]))
  }, [csTable])

  useEffect(() => {
    if (!joinTableA) { setJoinColumnsA([]); return }
    domainApi.tableDetail(joinTableA).then((d) => setJoinColumnsA(d.columns)).catch(() => setJoinColumnsA([]))
  }, [joinTableA])

  useEffect(() => {
    if (!joinTableB) { setJoinColumnsB([]); return }
    domainApi.tableDetail(joinTableB).then((d) => setJoinColumnsB(d.columns)).catch(() => setJoinColumnsB([]))
  }, [joinTableB])

  // 일반 노트는 필드가 텍스트 하나뿐이라 행 안에서 바로 편집한다(코드셋/조인과 다른 흐름).
  const [editingGeneralId, setEditingGeneralId] = useState<string | null>(null)
  const [editingGeneralText, setEditingGeneralText] = useState('')

  const reload = () => {
    setLoading(true)
    setError(null)
    return domainApi.notes
      .list()
      .then(setNotes)
      .catch((e) => setError(e instanceof Error ? e.message : '조회 실패'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const grouped = useMemo(() => {
    const byCategory: Record<DomainNoteCategory, DomainNote[]> = { codeset: [], join: [], general: [] }
    for (const n of notes) byCategory[n.category]?.push(n)
    return byCategory
  }, [notes])

  const resetForm = () => {
    setEditingId(null)
    setGeneralTable(GENERAL_OPTION)
    setGeneralText('')
    setCsTable('')
    setCsColumn('')
    setCsCodesText('')
    setCsRemark('')
    setJoinTableA('')
    setJoinTableB('')
    setJoinColumnA('')
    setJoinColumnB('')
    setJoinRemark('')
  }

  const startEditStructured = (note: DomainNote) => {
    setEditingId(note.id)
    setFormCategory(note.category)
    if (note.category === 'codeset') {
      const d = note.structured_data as CodesetData
      setCsTable(d.table)
      setCsColumn(d.column)
      setCsCodesText(codesToText(d.codes))
      setCsRemark(d.remark ?? '')
    } else if (note.category === 'join') {
      const d = note.structured_data as JoinData
      setJoinTableA(d.tables[0])
      setJoinTableB(d.tables[1])
      setJoinColumnA(d.columns[0])
      setJoinColumnB(d.columns[1])
      setJoinRemark(d.remark ?? '')
    }
  }

  const handleSubmit = async () => {
    setSaving(true)
    setError(null)
    try {
      if (formCategory === 'general') {
        const text = generalText.trim()
        if (!text) return
        await domainApi.notes.create(generalTable === GENERAL_OPTION ? null : generalTable, text, 'general', null)
      } else if (formCategory === 'codeset') {
        const codes = parseCodes(csCodesText)
        if (!csTable || !csColumn.trim() || Object.keys(codes).length === 0) {
          setError('대상 테이블·컬럼·코드셋(최소 1줄)을 모두 입력하세요.')
          return
        }
        const data: CodesetData = { table: csTable, column: csColumn.trim(), codes, remark: csRemark.trim() || null }
        const text = renderCodesetNote(data)
        if (editingId) {
          await domainApi.notes.update(editingId, text, data)
        } else {
          await domainApi.notes.create(csTable, text, 'codeset', data)
        }
      } else {
        if (!joinTableA || !joinTableB || joinTableA === joinTableB || !joinColumnA || !joinColumnB) {
          setError('테이블 A/B(서로 달라야 함)와 각 테이블의 조인 컬럼을 선택하세요.')
          return
        }
        const data: JoinData = {
          tables: [joinTableA, joinTableB],
          columns: [joinColumnA, joinColumnB],
          remark: joinRemark.trim() || null,
        }
        const text = renderJoinNote(data)
        if (editingId) {
          await domainApi.notes.update(editingId, text, data)
        } else {
          await domainApi.notes.create(null, text, 'join', data)
        }
      }
      resetForm()
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (noteId: string) => {
    setSaving(true)
    setError(null)
    try {
      await domainApi.notes.remove(noteId)
      if (editingId === noteId) resetForm()
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '삭제 실패')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveGeneralEdit = async (noteId: string) => {
    const text = editingGeneralText.trim()
    if (!text) return
    setSaving(true)
    setError(null)
    try {
      await domainApi.notes.update(noteId, text)
      setEditingGeneralId(null)
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '수정 실패')
    } finally {
      setSaving(false)
    }
  }

  const renderGeneralRow = (note: DomainNote) => (
    <div key={note.id} className="domain-note-row">
      {editingGeneralId === note.id ? (
        <div className="domain-note-edit">
          <textarea
            className="domain-note-textarea"
            value={editingGeneralText}
            onChange={(e) => setEditingGeneralText(e.target.value)}
            rows={3}
            autoFocus
          />
          <div className="domain-note-actions">
            <button className="btn-secondary" onClick={() => setEditingGeneralId(null)} disabled={saving}>취소</button>
            <button className="btn-primary" onClick={() => handleSaveGeneralEdit(note.id)} disabled={saving || !editingGeneralText.trim()}>
              저장
            </button>
          </div>
        </div>
      ) : (
        <>
          {note.table_name && <span className="domain-note-table-tag">{note.table_name}</span>}
          <p className="domain-note-text">{note.note}</p>
          <div className="domain-note-actions">
            <button
              className="btn-secondary"
              onClick={() => { setEditingGeneralId(note.id); setEditingGeneralText(note.note) }}
              disabled={saving}
            >
              수정
            </button>
            <button className="btn-danger-outline" onClick={() => handleDelete(note.id)} disabled={saving}>삭제</button>
          </div>
        </>
      )}
    </div>
  )

  const renderStructuredRow = (note: DomainNote) => (
    <div key={note.id} className="domain-note-row">
      <p className="domain-note-text">{note.note}</p>
      <div className="domain-note-actions">
        <button className="btn-secondary" onClick={() => startEditStructured(note)} disabled={saving}>수정</button>
        <button className="btn-danger-outline" onClick={() => handleDelete(note.id)} disabled={saving}>삭제</button>
      </div>
    </div>
  )

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>도메인 노트</h2>
          <p className="subtitle">
            SQL 생성이 참고하는 도메인 지식입니다. 코드셋/일반(테이블 지정 시)은 스키마 검색(벡터 임베딩)에도 함께 반영됩니다.
          </p>
          <button className="modal-close" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="modal-body">
          {error && <div className="run-error-banner">{error}</div>}

          <section className="domain-note-form">
            <div className="domain-note-category-tabs">
              {(Object.keys(CATEGORY_LABEL) as DomainNoteCategory[]).map((cat) => (
                <button
                  key={cat}
                  className={`domain-note-category-tab ${formCategory === cat ? 'active' : ''}`}
                  onClick={() => { if (!editingId) { setFormCategory(cat) } }}
                  disabled={!!editingId}
                >
                  {CATEGORY_LABEL[cat]}
                </button>
              ))}
              {editingId && <span className="domain-note-editing-hint">— 수정 중(카테고리 변경 불가)</span>}
            </div>

            {formCategory === 'general' && (
              <>
                <select className="domain-note-select" value={generalTable} onChange={(e) => setGeneralTable(e.target.value)}>
                  <option value={GENERAL_OPTION}>전체 도메인 (일반 규칙)</option>
                  {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                </select>
                <textarea
                  className="domain-note-textarea"
                  placeholder="예: s_patno는 명시적 요청 없으면 SELECT에 노출하지 마라"
                  value={generalText}
                  onChange={(e) => setGeneralText(e.target.value)}
                  rows={2}
                />
              </>
            )}

            {formCategory === 'codeset' && (
              <>
                <div className="domain-note-form-row">
                  <select
                    className="domain-note-select"
                    value={csTable}
                    onChange={(e) => { setCsTable(e.target.value); setCsColumn('') }}
                  >
                    <option value="">대상 테이블 선택…</option>
                    {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                  </select>
                  <select
                    className="domain-note-select"
                    value={csColumn}
                    onChange={(e) => setCsColumn(e.target.value)}
                    disabled={!csTable}
                  >
                    <option value="">{csTable ? '대상 컬럼 선택…' : '테이블을 먼저 선택하세요'}</option>
                    {csColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <input
                  className="domain-note-input"
                  placeholder="코드=의미, 코드=의미 (쉼표로 구분) — 예: ADT001=호르몬 치료(항남성호르몬요법), ADT002=호르몬 치료(항남성호르몬요법)"
                  value={csCodesText}
                  onChange={(e) => setCsCodesText(e.target.value)}
                />
                <textarea
                  className="domain-note-textarea"
                  placeholder="비고 (선택 — 예: 판정은 mark_rslt_val 컬럼 사용)"
                  value={csRemark}
                  onChange={(e) => setCsRemark(e.target.value)}
                  rows={2}
                />
              </>
            )}

            {formCategory === 'join' && (
              <>
                <div className="domain-note-form-row">
                  <select
                    className="domain-note-select"
                    value={joinTableA}
                    onChange={(e) => { setJoinTableA(e.target.value); setJoinColumnA('') }}
                  >
                    <option value="">테이블 A 선택…</option>
                    {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                  </select>
                  <select
                    className="domain-note-select"
                    value={joinColumnA}
                    onChange={(e) => setJoinColumnA(e.target.value)}
                    disabled={!joinTableA}
                  >
                    <option value="">{joinTableA ? '컬럼 선택…' : '테이블을 먼저 선택하세요'}</option>
                    {joinColumnsA.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <div className="domain-note-form-row">
                  <select
                    className="domain-note-select"
                    value={joinTableB}
                    onChange={(e) => { setJoinTableB(e.target.value); setJoinColumnB('') }}
                  >
                    <option value="">테이블 B 선택…</option>
                    {tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                  </select>
                  <select
                    className="domain-note-select"
                    value={joinColumnB}
                    onChange={(e) => setJoinColumnB(e.target.value)}
                    disabled={!joinTableB}
                  >
                    <option value="">{joinTableB ? '컬럼 선택…' : '테이블을 먼저 선택하세요'}</option>
                    {joinColumnsB.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </select>
                </div>
                <textarea
                  className="domain-note-textarea"
                  placeholder="비고 (선택 — 예: 치료 상세는 스냅샷 컬럼 대신 이 조인으로 확인)"
                  value={joinRemark}
                  onChange={(e) => setJoinRemark(e.target.value)}
                  rows={2}
                />
              </>
            )}

            <div className="domain-note-actions">
              {editingId && <button className="btn-secondary" onClick={resetForm} disabled={saving}>취소</button>}
              <button
                className="btn-primary"
                onClick={handleSubmit}
                disabled={saving || (formCategory === 'general' && !generalText.trim())}
              >
                {editingId ? '저장' : '노트 추가'}
              </button>
            </div>
          </section>

          {loading && (
            <div className="skeleton-list">
              <div className="skeleton-line" />
              <div className="skeleton-line" />
            </div>
          )}

          {!loading && grouped[formCategory].length === 0 && (
            <div className="panel-empty">{CATEGORY_LABEL[formCategory]} 노트가 아직 없습니다.</div>
          )}

          {!loading && grouped[formCategory].length > 0 && (
            <div className="domain-note-group">
              {formCategory === 'general' ? grouped.general.map(renderGeneralRow) : grouped[formCategory].map(renderStructuredRow)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
