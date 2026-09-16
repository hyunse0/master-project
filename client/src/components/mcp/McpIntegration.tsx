import { useEffect, useState } from 'react'
import { domainApi } from '../../api/domainClient'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const MCP_URL = `${API_BASE.replace(/\/$/, '')}/mcp`

interface ToolParam {
  name: string
  type: string
  required: boolean
}

interface ToolSpec {
  name: string
  kind: 'read' | 'exec'
  desc: string
  guard?: string
  params: ToolParam[]
  response: string
}

// server/app/api/mcp.py의 실제 6개 tool과 1:1로 대응 — 파라미터/응답 예시는 그 구현이
// 실제로 반환하는 필드 그대로다(2026-08-30 로컬 mcp inspector 스모크테스트에서 캡처).
const TOOLS: ToolSpec[] = [
  {
    name: 'get_domain_status',
    kind: 'read',
    desc: '활성 도메인(domain_connections.is_active)의 DB 연결 상태를 반환합니다.',
    params: [],
    response: `{
  "domain": "poc_prostate",
  "connected": true,
  "error": null,
  "host": "localhost",
  "port": 5432,
  "dbname": "poc_prostate",
  "schemas": ["poc"]
}`,
  },
  {
    name: 'list_tables',
    kind: 'read',
    desc: '활성 도메인의 전체 테이블 목록(이름·코멘트·컬럼 수)을 반환합니다.',
    params: [],
    response: `[
  {
    "table": "poc.poc_prostate_patient_info",
    "schema": "poc",
    "name": "poc_prostate_patient_info",
    "comment": "전립선암 환자 코호트",
    "column_count": 22
  }
]`,
  },
  {
    name: 'get_table_detail',
    kind: 'read',
    desc: '테이블 하나의 컬럼·타입·코멘트·PK·외래키를 반환합니다.',
    params: [{ name: 'table_name', type: 'string', required: true }],
    response: `{
  "table": "poc.poc_prostate_patient_info",
  "comment": "전립선암 환자 코호트",
  "columns": [
    { "name": "cancer_reg_no", "type": "text",
      "comment": "암등록번호", "is_primary_key": false }
  ],
  "foreign_keys": []
}`,
  },
  {
    name: 'search_schema',
    kind: 'read',
    desc: '자연어 질의와 의미적으로 가까운 테이블을 스키마 인덱스(Qdrant)에서 검색합니다.',
    params: [
      { name: 'query', type: 'string', required: true },
      { name: 'limit', type: 'integer', required: false },
    ],
    response: `[
  {
    "table": "poc.poc_prostate_patient_info",
    "comment": "전립선암 환자 코호트",
    "score": 0.4707,
    "columns": ["cancer_reg_no", "crcn_cd", "..."]
  }
]`,
  },
  {
    name: 'search_few_shot_examples',
    kind: 'read',
    desc: '질문과 유사한 few-shot(질문→SQL) 예제를 검색합니다.',
    params: [
      { name: 'question', type: 'string', required: true },
      { name: 'top_k', type: 'integer', required: false },
      { name: 'domain', type: 'string', required: false },
    ],
    response: `[
  {
    "question": "전립선암 환자는 총 몇 명인가요?",
    "sql": "SELECT COUNT(DISTINCT s_patno) FROM poc.poc_prostate_patient_info",
    "tables": ["poc.poc_prostate_patient_info"],
    "score": 0.4816
  }
]`,
  },
  {
    name: 'run_nl2sql_query',
    kind: 'exec',
    desc: '자연어 질문을 SQL로 변환·검증·실행해 결과를 반환합니다.',
    guard: '자동 모드 고정 — 스키마 인용·값 앵커 검증 통과 시에만 실행됩니다',
    params: [
      { name: 'question', type: 'string', required: true },
      { name: 'domain', type: 'string', required: false },
    ],
    response: `{
  "run_id": "15a74d9e-84ad-42bb-9894-4c18d6bb6b51",
  "status": "success",
  "domain": "poc_prostate",
  "sql": "SELECT COUNT(DISTINCT s_patno) AS patient_count\\nFROM poc.poc_prostate_patient_info",
  "columns": ["patient_count"],
  "rows": [{ "patient_count": 8 }],
  "row_count": 1,
  "summary": "전립선암 환자는 총 8명입니다 ...",
  "execution_error": null
}`,
  },
]

const BADGE = {
  read: { label: '읽기전용' },
  exec: { label: '실행' },
}

const inspectorSnippet = `npx @modelcontextprotocol/inspector

# Inspector가 열리면 Transport에 Streamable HTTP를 고르고
# 아래 URL을 붙여넣습니다
${MCP_URL}`

const connectorSnippet = `{
  "mcpServers": {
    "nl2sql-agent": {
      "type": "http",
      "url": "${MCP_URL}"
    }
  }
}`

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).catch(() => {})
}

function CopyButton({ text, copiedKey, copied, onCopy }: { text: string; copiedKey: string; copied: string | null; onCopy: (key: string, text: string) => void }) {
  const isCopied = copied === copiedKey
  return (
    <button className={`btn-secondary mcp-copy-btn ${isCopied ? 'copied' : ''}`} onClick={() => onCopy(copiedKey, text)}>
      {isCopied ? '복사됨' : '복사'}
    </button>
  )
}

export function McpIntegration() {
  const [healthUp, setHealthUp] = useState<boolean | null>(null)
  const [activeDomain, setActiveDomain] = useState<string | null>(null)
  const [openTool, setOpenTool] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((res) => setHealthUp(res.ok))
      .catch(() => setHealthUp(false))

    domainApi
      .status()
      .then((s) => setActiveDomain(s.connected ? s.domain : null))
      .catch(() => setActiveDomain(null))
  }, [])

  const onCopy = (key: string, text: string) => {
    copyToClipboard(text)
    setCopied(key)
    setTimeout(() => setCopied((c) => (c === key ? null : c)), 1600)
  }

  const readCount = TOOLS.filter((t) => t.kind === 'read').length
  const execCount = TOOLS.filter((t) => t.kind === 'exec').length

  return (
    <>
      <header className="page-header">
        <h1>MCP 연동</h1>
        <p className="subtitle">외부 MCP 클라이언트가 이 에이전트에 붙는 방법과 노출된 tool을 안내합니다.</p>
      </header>

      <div className="content">
        {/* Zone 1 — 연결 정보 */}
        <section className="panel">
          <div className="panel-head">
            <h2>연결 정보</h2>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className={`mcp-health-dot ${healthUp === null ? 'checking' : healthUp ? 'up' : 'down'}`} />
              <span className={`mcp-health-label ${healthUp === null ? 'checking' : healthUp ? 'up' : 'down'}`}>
                {healthUp === null ? '확인 중' : healthUp ? '정상' : '응답 없음'}
              </span>
              <span className="panel-endpoint" style={{ marginLeft: 0 }}>GET /health</span>
            </div>
          </div>

          <div className="mcp-zone-body">
            <div className="mcp-field">
              <span className="mcp-field-label">MCP 엔드포인트</span>
              <div className="mcp-endpoint-box">
                <span className="mcp-endpoint-value">{MCP_URL}</span>
                <CopyButton text={MCP_URL} copiedKey="url" copied={copied} onCopy={onCopy} />
              </div>
              <span className="mcp-field-hint">API 서버(VITE_API_URL) 기준으로 계산된 값입니다.</span>
            </div>

            <div className="mcp-info-row">
              <div className="mcp-info-card">
                <span className="mcp-info-label">전송 방식</span>
                <span className="mcp-info-value">Streamable HTTP</span>
              </div>
              <div className="mcp-info-card">
                <span className="mcp-info-label">서버 상태</span>
                <span className={`mcp-info-value ${healthUp === null ? '' : healthUp ? 'up' : 'down'}`}>
                  {healthUp === null ? '상태 확인 중…' : healthUp ? 'MCP 포함 정상 응답' : '서버에 연결할 수 없습니다'}
                </span>
              </div>
              <div className="mcp-info-card accent">
                <span className="mcp-info-label accent">현재 활성 도메인</span>
                <span className="mcp-info-value accent-strong">{activeDomain ?? '-'}</span>
                <span className="mcp-field-hint accent">모든 tool은 이 도메인 기준으로 응답합니다. 도메인이 바뀌면 tool 응답도 함께 바뀝니다.</span>
              </div>
            </div>
          </div>
        </section>

        {/* Zone 2 — 연결 방법 */}
        <section className="panel">
          <div className="panel-head">
            <h2>연결 방법</h2>
            <span className="panel-count">클라이언트별 예시</span>
          </div>

          <div className="mcp-zone-body">
            <div className="mcp-snippet">
              <div className="mcp-snippet-head">
                <span className="mcp-snippet-title">MCP Inspector</span>
                <span className="mcp-snippet-note">터미널에서 실행 후 URL 붙여넣기</span>
                <div style={{ flex: 1 }} />
                <CopyButton text={inspectorSnippet} copiedKey="inspector" copied={copied} onCopy={onCopy} />
              </div>
              <pre className="sql-view-box">{inspectorSnippet}</pre>
            </div>

            <div className="mcp-snippet">
              <div className="mcp-snippet-head">
                <span className="mcp-snippet-title">Claude Desktop · Claude Code 등 커스텀 커넥터</span>
                <span className="mcp-snippet-note">설정 파일에 추가</span>
                <div style={{ flex: 1 }} />
                <CopyButton text={connectorSnippet} copiedKey="connector" copied={copied} onCopy={onCopy} />
              </div>
              <pre className="sql-view-box">{connectorSnippet}</pre>
            </div>

            <div className="mcp-notice warn">
              <span className="mcp-notice-icon">!</span>
              <span>MCP는 세션 프로토콜이라 일반 curl로는 테스트되지 않습니다. 위 클라이언트를 사용하세요.</span>
            </div>
          </div>
        </section>

        {/* Zone 3 — 노출된 tool */}
        <section className="panel">
          <div className="panel-head">
            <h2>노출된 tool</h2>
            <span className="panel-count">
              {TOOLS.length} tools · 읽기전용 {readCount} · 실행 {execCount}
            </span>
          </div>

          <div className="mcp-tool-list">
            {TOOLS.map((t) => {
              const isOpen = openTool === t.name
              return (
                <div className={`mcp-tool-card ${t.kind}`} key={t.name}>
                  <div className="mcp-tool-head">
                    <div className="mcp-tool-head-main">
                      <div className="mcp-tool-name-row">
                        <span className="mcp-tool-name">{t.name}</span>
                        <span className={`mcp-tool-badge ${t.kind}`}>{BADGE[t.kind].label}</span>
                        {t.guard && <span className="mcp-tool-guard">{t.guard}</span>}
                      </div>
                      <span className="mcp-tool-desc">{t.desc}</span>
                    </div>
                    <button className="btn-secondary" onClick={() => setOpenTool(isOpen ? null : t.name)}>
                      {isOpen ? '응답 예시 접기' : '응답 예시 보기'}
                    </button>
                  </div>

                  <div className="mcp-tool-body">
                    <span className="mcp-tool-section-label">PARAMETERS</span>
                    {t.params.length > 0 ? (
                      <div className="mcp-param-table">
                        <div className="mcp-param-row head">
                          <span>NAME</span>
                          <span>TYPE</span>
                          <span>REQUIRED</span>
                        </div>
                        {t.params.map((p) => (
                          <div className="mcp-param-row" key={p.name}>
                            <span className="mcp-param-name">{p.name}</span>
                            <span className="mcp-param-type">{p.type}</span>
                            <span className={`mcp-param-req ${p.required ? 'required' : ''}`}>{p.required ? '필수' : '선택'}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="mcp-param-none">파라미터 없음</span>
                    )}

                    {isOpen && (
                      <div className="mcp-response">
                        <span className="mcp-tool-section-label">RESPONSE EXAMPLE</span>
                        <pre className="sql-view-box">{t.response}</pre>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>
    </>
  )
}
