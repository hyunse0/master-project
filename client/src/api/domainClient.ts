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

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new Error(`${path} 요청 실패: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const domainApi = {
  status: () => getJSON<DomainStatus>('/domain/status'),
  tables: () => getJSON<TableSummary[]>('/domain/tables'),
  tableDetail: (table: string) => getJSON<TableDetail>(`/domain/tables/${encodeURIComponent(table)}`),
  schemaSearch: (q: string) => getJSON<SchemaSearchResult[]>(`/domain/schema-search?q=${encodeURIComponent(q)}`),
}
