const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface DomainStatus {
  domain: string
  connected: boolean
  error: string | null
  host: string
  port: number
  dbname: string
  schemas: string[]
}

export interface TableSummary {
  table: string
  schema: string
  name: string
  comment: string | null
  column_count: number
}

export interface TableColumn {
  name: string
  type: string
  comment: string | null
  is_primary_key: boolean
}

export interface ForeignKey {
  column: string
  ref_table: string
  ref_column: string
}

export interface TableDetail {
  table: string
  comment: string | null
  columns: TableColumn[]
  foreign_keys: ForeignKey[]
}

export interface SchemaSearchResult {
  table: string
  comment: string | null
  score: number
  columns: string[]
}

export type DomainNoteCategory = 'codeset' | 'join' | 'general'

export interface CodesetData {
  table: string
  column: string
  codes: Record<string, string>
  remark: string | null
}

export interface JoinData {
  tables: [string, string]
  columns: [string, string]
  remark: string | null
}

export interface DomainNote {
  id: string
  domain: string
  table_name: string | null
  category: DomainNoteCategory
  structured_data: CodesetData | JoinData | null
  note: string
  created_at: string
  updated_at: string
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(`${path} 요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const domainApi = {
  status: () => getJSON<DomainStatus>('/domain/status'),
  tables: () => getJSON<TableSummary[]>('/domain/tables'),
  tableDetail: (table: string) => getJSON<TableDetail>(`/domain/tables/${encodeURIComponent(table)}`),
  schemaSearch: (q: string) => getJSON<SchemaSearchResult[]>(`/domain/schema-search?q=${encodeURIComponent(q)}`),

  notes: {
    list: () => getJSON<DomainNote[]>('/domain/notes'),

    create: (
      tableName: string | null,
      note: string,
      category: DomainNoteCategory = 'general',
      structuredData: CodesetData | JoinData | null = null,
    ): Promise<DomainNote> =>
      fetch(`${API_BASE}/domain/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_name: tableName, note, category, structured_data: structuredData }),
      }).then(handle<DomainNote>),

    update: (noteId: string, note: string, structuredData: CodesetData | JoinData | null = null): Promise<DomainNote> =>
      fetch(`${API_BASE}/domain/notes/${noteId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note, structured_data: structuredData }),
      }).then(handle<DomainNote>),

    remove: (noteId: string): Promise<{ deleted: boolean }> =>
      fetch(`${API_BASE}/domain/notes/${noteId}`, { method: 'DELETE' }).then(handle<{ deleted: boolean }>),
  },
}
