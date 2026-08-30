# Data Access Copilot — master-project 이관/구축 계획

## Context

`master-project`에는 현재 UI 프로토타입 HTML(`data-access-copilot-prototype.html`) 한 개만 있고 `server`/`client` 디렉토리는 아직 없다. 목표는 이 프로토타입을 목표 UI로 삼아, 첨부된 "Data Access Copilot" 구현 스펙(LangGraph 기반 NL2SQL + schema/SQL 두 지점 human-in-the-loop)을 새로 구축하는 것이다.

기존 `rag-practice/server/sqlgen`에 이미 동작하는 NL2SQL 구현이 있지만, 두 차례의 코드 탐색으로 확인한 결과:
- **Postgres/pgvector 전제**인 부분(스키마 조회, few-shot 저장소)이 많다 — 초기엔 스펙의 SQLite 예시를 따라가려 했으나, 이후 "실제 운영 DB에 접속 정보만 연결하면 스키마를 읽어 RAG를 구축한다"는 요구사항으로 **DB를 Postgres로 확정**했다(아래 1번 섹션 참고). 결과적으로 few-shot 저장소만 Qdrant로 교체하면 되고, 스키마 조회 로직은 원본에 더 가깝게 재사용 가능해졌다.
- **전립선암 전용 도메인**(`schema_explorer.py`의 휴리스틱, `prompt_builder.py`의 시스템 프롬프트, 데이터셋 자체)이라 새 스펙의 범용 임상 스키마(patients/diagnoses/encounters/departments/medications/lab_results/physicians/appointments)와 테이블명이 전혀 겹치지 않는다 — 데이터셋은 완전 신규 제작.
- 기존 UI/API는 **interrupt/resume 패턴이 전혀 없는** 단발성 스트리밍 구조라 새 스펙의 human-in-the-loop 요구와는 아키텍처가 다르다 — 신규 설계 필요.

따라서 "복사"는 파일 단위 이관이 아니라 **재사용 등급별 분류**로 접근한다: (A) 거의 그대로 복사, (B) 로직 재사용 + DB계층 재작성, (C) 패턴만 참고해 새로 작성, (D) 완전 신규. LangGraph의 interrupt/resume을 FastAPI 요청-응답에 연결하는 핵심 메커니즘은 별도로 설계 검증을 거쳤다(아래 5번 섹션).

이후 "기술적 깊이가 더 필요하다"는 피드백을 받아, 8주 스코프 안에서 비용 대비 효과가 높은 항목들을 추가 채택했다(아래 1번 섹션). 핵심 NL2SQL 파이프라인 설계(재사용 매핑·LangGraph interrupt/resume 메커니즘)는 이 확장과 무관하게 그대로 유효하다.

---

## 1. 스코프 우선순위 확정 (피드백 반영)

원래 8주 계획(코어 파이프라인 → 트레이스 UI → HITL → 교정 학습 루프)에 아래 항목들을 비용 대비 효과로 걸러 재배치한다.

### 채택 (Tier 1 — 거의 공짜, 기존 설계에 얹기만 하면 됨)
- **토큰 이코노미 대시보드**: 이미 설계된 "전체 스키마 덤프 대신 Qdrant 검색으로 컨텍스트 축소"를 숫자로 증명. LLM 호출 지점에 토큰 카운팅만 추가하면 되는 로깅 작업.
- **질의 난이도별 모델 라우팅**: `intent_node`에 난이도 태그(easy/medium/hard)만 추가하고, 그 값으로 저비용/고성능 모델을 분기. 토큰 대시보드와 묶여 "비용-정확도 트레이드오프" 실험이 자연스럽게 나옴.

### 채택 (Tier 2 — 비용 있음, "기술적 깊이" 지적에 직접 대응)
- **MCP 서버 노출**: FastAPI로 이미 만든 도구 함수들을 MCP 서버로 래핑. 재사용 가능한 아키텍처 목표와 직결.
- **멀티 에이전트 구조 확장**: 완전 신규가 아니라, 기존 "의도분류→분기" 구조에 **질의 유형(집계형/리스트형/코호트형) 분류**를 얹고 `sql_generation_node`를 유형별 전문 프롬프트/도구를 가진 서브 에이전트로 승격. 그래프 골격 재사용.

### 채택 (Tier 2.5 — 프론트 전용, 백엔드 스코프와 독립)
- **결과 시각화 고도화**: 결과 형태(집계/단건/시계열)에 따라 차트 종류 자동 선택.

### 보류/축소 (Tier 3)
- **권한별 기능 관리(RBAC)**: 실제 인증/권한 구현은 제외. "역할 선택 시 조회 가능 도메인이 달라지는" 정도의 목업 토글로 축소하거나 Out of Scope로 명시.
- **설정 항목 확대**: 채택하지 않음 — 평가 기준이 "좁고 깊게"를 명시하므로 토글 개수 늘리기는 역효과.

### Stretch goal로 후순위 배치
- **교정 사례 학습 루프**(사용자가 수정한 스키마/SQL을 few-shot 저장소에 재투입하는 RAG 기반 축적): 아이디어 자체는 유효하지만, 지금 피드백이 요구하는 "기술적 깊이·다양성"에는 멀티에이전트·MCP가 더 직접적으로 어필하므로 8주 코어 스코프 밖으로 이동.

### 데이터 우려 대응
"데이터가 약하다"는 지적의 정확한 의미(합성 데이터 신뢰성 / 규모가 작음 / 실제 병원 스키마의 지저분함 부재)는 리뷰어에게 직접 확인 필요. 다만 공통 대응은 기획서에 이미 있는 "왜 이 규모로 통제했는지"를 발표에서 선제적으로 짚고 트레이드오프를 설명하는 것 — 애매하게 넘기면 약점, 먼저 인정하면 전략 렌즈 점수.

---

## 2. 재사용 매핑 (rag-practice → master-project/server)

> **DB를 Postgres로 확정하면서 바뀐 것**: "도메인 = 손으로 쓴 `schema.yaml`"이 아니라 **"도메인 = 접속 정보로 연결된 실제 Postgres DB"**로 개념이 바뀌었다. 스키마는 매번 `information_schema`/`pg_description`/FK 제약을 조회해 실시간으로 읽고, 그 결과를 임베딩해 Qdrant에 색인하는 방식(스키마 인덱서, 아래 D)으로 RAG를 구축한다. 그 결과 아래 재사용 매핑도 SQLite 우회 없이 원본에 더 가깝게 재사용 가능해졌다.

### A. 거의 그대로 복사 (도메인/DB 비의존)
| 원본 | 대상 | 비고 |
|---|---|---|
| `server/docrag/dense_embedder.py`의 `EmbeddingEngine` | `server/app/embedding/embedder.py` | BAAI/bge-m3, 한국어 지원, 완전 범용 — 그대로 복사 |
| `server/sqlgen/canonicalizer.py` | `server/app/sql/canonicalizer.py` | `dialect="postgres"` 그대로 — 원본과 동일하게 사용 |
| `server/sqlgen/validator.py` | `server/app/sql/validator.py` | SELECT-only 검사, `dialect="postgres"` 그대로 — 원본과 동일하게 사용 |

### B. 로직 재사용, 접속 정보 파라미터화만 필요
| 원본 | 대상 | 변경 사항 |
|---|---|---|
| `server/sqlgen/schema_provider.py` | `server/app/sql/schema_provider.py` | `information_schema`+`pg_description` 조회 로직 그대로 유지. 하드코딩된 DSN과 `allowed_schemas=["poc"]` 대신 **도메인별 접속 설정(호스트/포트/dbname/allowed_schemas)을 파라미터로 주입**하도록 일반화 |
| `server/sqlgen/value_anchor.py` | `server/app/sql/value_anchor.py` | psycopg2 로직 그대로 유지, 코드컬럼 휴리스틱(`_cd`/`_nm`)만 새 스키마에 맞게 재정의(혹은 실 DB 컨벤션에 맞춰 설정화) |
| `server/sqlgen/schema_citation_validator.py` | `server/app/sql/schema_citation_validator.py` | alias/CTE 해석 + `information_schema` 조회 로직 그대로 유지 |
| `server/sqlgen/retriever.py` | `server/app/sql/retriever.py` | 하이브리드 스코어링(0.5 semantic+0.3 table jaccard+0.2 domain) 로직 유지, 저장소만 Qdrant로 교체 |
| `db/05_seed_sql_knowledge.py` | `server/scripts/seed_few_shot.py` | question/intent/sql/tables/metrics/domain 필드 구조 유지, 저장소를 Qdrant 컬렉션(`sql_knowledge_{domain}`)으로 교체, `--domain` 인자로 도메인 팩의 `few_shot.json`을 읽도록 일반화 |
| `db/04_apply_schema.py` | (대응 없음) | 우리가 스키마를 만들어 적용하는 게 아니라 **이미 존재하는 실 DB에 연결**하는 구조라 이 스크립트 자체가 불필요해짐. 대신 `server/scripts/test_connection.py`(신규) — 접속 정보로 연결해 introspection 결과를 눈으로 확인하는 스모크테스트 스크립트 |
| `server/generation/llm_client.py` | `server/app/llm/gemini_client.py` (+ `base.py` 인터페이스) | 캐싱 패턴은 재사용, `generate/generate_stream` 인터페이스로 감싸 vLLM 교체 가능하게 |

### C. 패턴만 참고, 내용은 새로 작성
- `server/sqlgen/schema_explorer.py` → **FK 2-hop 추적·값 샘플링(introspection) 부분**은 새 `schema_indexer.py`(아래 D)에 직접 참고할 만큼 가까워졌다. 다만 전립선암 전용 휴리스틱(도메인 용어, `_cd`/`_nm` 컬럼명 규칙, "논리 매핑:" 코멘트 컨벤션 파싱)은 그대로 가져오지 않고, 실 DB에 FK가 없을 때의 대체 수단으로만 개념 참고
- `server/sqlgen/prompt_builder.py` → 구조적 패턴(시스템+스키마+예제+재시도 피드백 블록, `VALUE_UNCONFIRMED` 탈출구)은 공통 템플릿으로 유지하되, 도메인 특화 문구는 도메인 팩의 `prompt_fragments.yaml`에서 읽어와 템플릿에 주입
- `server/sqlgen/pipeline.py`, `server/service/ask_service.py`, `server/retrieval/router.py` → 노드 책임 분리 참고용, 실제로는 LangGraph 그래프가 대체
- `ui/tabs/sqlgen/debug_sql.py`의 스테이지/attempts 렌더링 → `GET /runs/{id}/trace` 응답 설계 및 React 스테이지 레일 참고
- `server/chatgraph/graph.py`, `server/api/dependencies.py`, `server/api/routes/chat_session.py` → **LangGraph 배선 방식(체크포인터 생성, `thread_id` 매핑, `get_stream_writer()` 커스텀 이벤트)**의 실제 동작 예시로 직접 참고 — 체크포인터도 이제 원본처럼 **PostgresSaver**를 그대로 참고(아래 5번 섹션 갱신)

### D. 완전 신규
- **도메인 팩 로더 (엔진 쪽 이음새, 재사용성의 핵심)**: `DOMAIN` 설정값 → 이제 `schema.yaml` 경로가 아니라 **도메인별 Postgres 접속 설정(호스트/포트/dbname/allowed_schemas)** 해석, Qdrant 컬렉션명 파라미터화(`sql_knowledge_{domain}`, `schema_{domain}`) — **완료**(`app/domain/loader.py`), 빈 Postgres에 임의 테이블 하나로 스모크테스트 완료
- **스키마 introspection (`schema_provider.py`)**: 접속된 Postgres에서 `information_schema`+`pg_catalog`(`pg_statio_all_tables`+`pg_description`)로 테이블/컬럼/코멘트/PK/FK를 읽어 텍스트로 변환 — **완료**, 스모크테스트로 코멘트·PK·FK 인식까지 확인
- **스키마 인덱서 (완료, "접속 정보만 주면 RAG 구축"의 나머지 절반)**: `schema_provider`가 만든 테이블별 텍스트를 임베딩해 Qdrant `schema_{domain}` 컬렉션에 색인. `poc_prostate` 16테이블 색인 + 실제 질의 검색 검증 완료. `schema_linking_node`가 질의 시점에 여기서 검색(다음 작업)
- **실제 데이터셋/스키마는 사용자가 별도로 제공** — `db/01~03_*.sql`(전립선암 마트)이나 8테이블 clinical_v1 합성 데이터셋은 만들지 않기로 함(초안으로 만들었다가 폐기). 대신 위 로더/introspection이 **어떤 Postgres 스키마가 와도** 동작하도록 범용으로 설계됐고, 실제 접속 정보가 오면 그대로 연결
- Golden query set — 실제 데이터셋이 확정된 뒤 그에 맞춰 작성 (지금은 보류)
- LangGraph 그래프/노드, FastAPI `/runs` 엔드포인트, React 프론트엔드 — 전부 신규

---

## 3. 디렉토리 구조

```
master-project/
├── data-access-copilot-prototype.html   (유지 — 디자인 레퍼런스)
├── docker-compose.yml                    (Postgres + Qdrant)
├── server/
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── routes.py            # POST /runs, GET /runs/{id}, POST /runs/{id}/resume, GET /runs/{id}/trace
│   │   │   ├── mcp.py               # MCP 서버 노출 (Tier2) — 아래 도구 함수들을 MCP tool로 래핑
│   │   │   └── schemas.py
│   │   ├── graph/
│   │   │   ├── state.py             # GraphState — 스펙 3.2 + difficulty/query_type 확장(1번 섹션)
│   │   │   ├── build.py             # StateGraph 조립, 체크포인터 바인딩
│   │   │   └── nodes/
│   │   │       ├── intent.py            # 의도분류 + 난이도 태그(easy/med/hard) + 질의유형(집계/리스트/코호트)
│   │   │       ├── schema_linking.py
│   │   │       ├── schema_review.py     # interrupt() 전용, 얇은 노드
│   │   │       ├── sql_generation/      # 질의유형별 서브에이전트 (Tier2 멀티에이전트)
│   │   │       │   ├── aggregate.py
│   │   │       │   ├── list.py
│   │   │       │   └── cohort.py
│   │   │       ├── sql_review.py        # interrupt() 전용, 얇은 노드
│   │   │       ├── validation.py
│   │   │       └── execution.py
│   │   ├── sql/            # canonicalizer/validator/citation/value_anchor/schema_provider/retriever/prompt_builder
│   │   │   ├── schema_provider.py    # 도메인 접속 설정으로 실 Postgres를 introspect (schema.yaml 없음)
│   │   │   └── prompt_builder.py     # 공통 템플릿 + domains/<domain>/prompt_fragments.yaml 주입
│   │   ├── llm/
│   │   │   ├── base.py              # 인터페이스 + 토큰 카운팅 래퍼(Tier1, 모든 generate() 호출 계측)
│   │   │   ├── gemini_client.py
│   │   │   └── router.py            # 난이도별 모델 라우팅 (Tier1)
│   │   ├── embedding/embedder.py
│   │   ├── knowledge/
│   │   │   ├── qdrant_connection.py  # Qdrant 클라이언트 헬퍼 (모듈명이 패키지명과 겹치면 self-import 되므로 qdrant_client.py 금지)
│   │   │   ├── qdrant_store.py       # few-shot 저장소, 컬렉션명 = sql_knowledge_{domain}
│   │   │   └── schema_indexer.py     # 완료 — DB introspection → 임베딩 → schema_{domain} 컬렉션에 색인
│   │   ├── db/postgres_client.py
│   │   ├── db/app_db.py              # 완료 — 앱 자체 운영 DB(app-db) 접속. 타겟 도메인 DB와 별개, 고정 접속정보
│   │   ├── db/schema.sql              # 완료 — app-db DDL (runs, domain_connections 테이블). PostgresSaver 체크포인트 테이블은 미포함(6번 항목에서 setup()이 자동 생성)
│   │   ├── db/encryption.py           # 완료 — domain_connections.db_password_enc 암복호화 (Fernet, APP_SECRET_KEY)
│   │   ├── domain/loader.py              # 완료 — domain_connections 테이블에서 접속정보 조회(활성 도메인 자동 탐색), 도메인 팩 경로/Qdrant 컬렉션명 해석은 그대로 (재사용성 이음새)
│   │   ├── observability/cost_tracker.py # run별 토큰/비용 인메모리 버퍼 (trace와 동일한 방식으로 state 밖에서 추적)
│   │   └── runs/run_manager.py           # run_id 존재확인 registry + 상태 파생 헬퍼
│   ├── domains/                      # 지금은 비어있음 — 실제 접속 정보/데이터가 오면 여기에 도메인 팩 생성
│   │   └── <domain_name>/            # ddl.sql·synthetic_data.py는 없음(스키마는 DB에서 직접 읽음). 사람이 채우는 건:
│   │       ├── few_shot.json         #   질문→SQL 예제 (자동 생성 불가)
│   │       ├── golden_set.json       #   평가용 골든셋 (자동 생성 불가)
│   │       └── prompt_fragments.yaml #   도메인 특화 프롬프트 조각
│   ├── scripts/
│   │   ├── test_connection.py    # --domain 인자로 연결·introspection 스모크테스트 (완료)
│   │   ├── init_app_db.py        # app-db에 schema.sql 적용, 재실행해도 안전 (완료)
│   │   ├── register_domain.py    # 도메인 접속정보를 domain_connections에 등록/교체 + 도메인 팩 폴더 생성 (완료)
│   │   └── seed_few_shot.py      # --domain 인자로 해당 팩의 few_shot.json을 Qdrant에 시딩
│   ├── eval/ (execution_accuracy.py, condition_summary_faithfulness.py, schema_mapping_accuracy.py, self_correction_ablation.py, token_cost_comparison.py)
│   └── tests/
└── client/
    ├── package.json            # Vite + React + TypeScript
    ├── index.html
    └── src/
        ├── App.tsx
        ├── styles/tokens.css   # 프로토타입 :root 변수 그대로 포팅
        ├── api/runsClient.ts
        ├── state/useRunStore.ts   # STAGES/reviewConfig/candidates/status 전이를 상태로 포팅
        ├── components/
        │   ├── Sidebar.tsx, Topbar.tsx, ModeToggle.tsx, QueryCard.tsx, StageRail.tsx
        │   ├── stages/{Intent,SchemaLinking,SqlGeneration,Validation,Execution}Stage.tsx
        │   ├── SchemaGraph.tsx     # SVG, 노드셋 그대로(프로토타입이 이미 8개 테이블과 일치)
        │   ├── ResultChart.tsx    # 결과 형태별 차트 자동 선택 (Tier2.5)
        │   ├── CostDashboard.tsx  # 토큰/비용 패널 (Tier1)
        │   └── GoldenSetPanel.tsx
        └── types.ts
```

---

## 4. 프론트엔드 포팅 매핑 (프로토타입 → React)

프로토타입의 하드코딩된 mock 로직을 실제 API 연동으로 교체하는 1:1 대응:

| 프로토타입 요소 | React 대응 |
|---|---|
| `:root` CSS 변수 | `styles/tokens.css`로 변경 없이 복사 (디자인 확정본) |
| `.stage[data-status]` (idle/running/review/auto/approved) 전이 | 각 스테이지 컴포넌트의 `status` state, `setTimeout` mock 대신 `GET /runs/{id}` 응답으로 갱신 |
| `reviewConfig{schema,sql}` + 모드 pill(자동/단계검토/직접설정) | `POST /runs`의 `review_config` 바디 필드로 그대로 매핑 |
| `candidates[]` 체크박스 목록 (하드코딩) | 백엔드 `schema_candidates` (동적), 체크 상태를 `resume` 호출 시 `confirmed_schema`로 전송 |
| `sqlBox` textarea (검토 단계에서만 활성화) | 백엔드 `sql` 필드, `status==='review'`일 때만 편집 가능, 승인 시 `POST /runs/{id}/resume {sql}` |
| 참조 스키마 SVG 그래프 (8개 노드: patients/diagnoses/encounters/depts/meds/labs/physicians/appts) | **노드 구성이 이미 목표 스키마 8테이블과 정확히 일치** — 좌표/구조 그대로, `confirmed_schema`에 포함된 테이블만 `.on` 클래스 토글 |
| Golden set 정확도 바(정적 63/84/96%) | eval 스크립트 실행 결과를 반환하는 별도 엔드포인트/정적 JSON으로 연동 |
| summary banner | `execution_result` + `condition_summary` 렌더링 |
| (프로토타입에 없음, 신규) | `ResultChart.tsx`: 실행 결과 형태(집계/단건/시계열)에 따라 bar/table/line 자동 선택 |
| (프로토타입에 없음, 신규) | `CostDashboard.tsx`: run별 토큰 사용량, 스키마 검색 도입 전/후 비교, 난이도별 모델 분기 현황 |

---

## 5. LangGraph interrupt/resume 핵심 설계 (검증 완료)

가장 리스크가 큰 부분이라 별도 설계 검증을 거쳤다. 핵심 결정:

1. **인터럽트 지점은 "작업 노드"와 "검토 노드"를 분리한다.** `interrupt()`로 재개하면 그 노드 함수가 처음부터 다시 실행되므로, LLM 스코어링 같은 비용이 큰/비결정적 작업과 `interrupt()` 호출을 같은 함수에 두면 재개마다 재실행된다. → `schema_linking_node`(작업, commit) → `schema_review_node`(interrupt만 호출) → `sql_generation_node`(작업, commit) → `sql_review_node`(interrupt만 호출) → `validation_node` 순으로 그래프를 짠다.
2. **체크포인터는 PostgresSaver 사용** (`langgraph.checkpoint.postgres`). 데이터셋 DB 자체가 Postgres로 확정되면서 rag-practice의 `get_chat_checkpointer()` 배선 패턴을 그대로 재사용할 수 있게 됐다 — SQLite를 별도로 끌어올 이유가 사라짐(엔진 하나로 통일, 원본 패턴 재사용). MemorySaver는 프로세스 재시작 시 검토 대기 중인 run이 전부 사라지므로 배제.
3. **`run_id` = `thread_id`** (`f"nl2sql-{run_id}"` 네임스페이스만 접두). 별도 매핑 테이블 불필요하나, "존재하지 않는 run"과 "빈 상태"를 구분하기 위한 최소 `runs` registry(run_id, created_at, review_config, status_cache)는 필요.
   - **완료 — app-db 설계·인프라 구축**: 위 registry와 PostgresSaver 체크포인트를 담을 Postgres를 타겟 도메인 DB와 분리된 별도 서비스로 뒀다(`docker-compose.yml`의 `app-db`, 호스트 포트 5433, DB명 `nl2sql_app`) — 도메인이 바뀌거나 외부 DB로 교체돼도 앱 운영 데이터는 남아있어야 하기 때문. `runs` 테이블 컬럼: `run_id(uuid pk) / domain / question / review_config(jsonb) / status / created_at / updated_at`. 접속 설정은 `app/db/app_db.py`(`APP_DB_*` env), DDL은 `app/db/schema.sql`, 적용은 `scripts/init_app_db.py` — 컨테이너 기동·스키마 적용·`\d runs`로 확인 완료. PostgresSaver 체크포인트 테이블은 이 스키마에 포함하지 않음 — 6번 항목(Interrupt/resume 추가) 구현 시 `PostgresSaver.setup()`이 같은 app-db에 자동 생성. 비용/토큰 로그는 계획대로 인메모리 유지(대시보드 영속성 필요해지면 별도 `token_usage` 테이블을 이 app-db에 추가하는 방향으로 확장).
   - **완료 — 타겟 도메인 접속정보도 app-db로 이관**: 처음엔 `.env`(`POC_PROSTATE_DB_*`)에 뒀었는데, 실서비스에서는 이 접속정보를 사용자가 화면에서 직접 입력하는 구조가 맞다고 판단해 뒤집었다 — "배포 시점 설정"이 아니라 "런타임 데이터"라 `.env`가 아니라 테이블이 맞음. `domain_connections` 테이블(`id / name / db_host / db_port / db_name / db_user / db_password_enc / db_schemas / is_active / created_at / updated_at`), `is_active`에 부분 유니크 인덱스(`WHERE is_active`)를 걸어 "에이전트가 쓰는 도메인은 항상 최대 1개"를 DB 제약으로 강제(화면에서 다중 도메인을 뺀 지난 결정을 데이터 레벨에서도 보장). 비밀번호는 평문 저장 금지 — `app/db/encryption.py`(Fernet, 키는 `APP_SECRET_KEY` env, DB 안에서 키를 다루지 않아 쿼리 로그 노출 위험 없음)로 암호화해 `db_password_enc`(bytea)에 저장. 등록/교체는 `scripts/register_domain.py`(도메인 팩 폴더까지 자동 생성). `app/domain/loader.py`의 `get_domain()`이 `.env` 대신 이 테이블을 읽도록 전면 교체 완료 — `name` 없이 호출하면 활성 도메인을 자동으로 찾음. `DOMAIN` env var는 더 이상 코드에서 안 읽으므로 `.env`/`.env.example`에서 제거. `/domain/status`·`/domain/tables`·`/domain/tables/{table}` 정상 동작 확인 + 활성 도메인이 없을 때 400 에러 경로까지 확인 완료.
4. **`resume`은 `Command(resume=payload)`로 호출**하며, 재개 시점은 정확히 `sql_review_node` 내부이므로 사용자가 수정한 SQL은 `sql_generation_node`를 다시 타지 않고(=재작성으로 덮이지 않고) 곧바로 `validation_node`로 흘러 반드시 검증을 통과해야 한다 — 스펙의 "검증 우회 금지" 요건을 코드 구조로 보장.
5. **재시도 분기**: `review_config.sql`이 켜져 있으면 검증 실패 시 무조건 `sql_review_node`로 되돌아가 사람에게 다시 보여준다(자동 재생성으로 사용자 입력을 덮지 않음). 꺼져 있으면 기존 스펙대로 `retry_count` 기반 자동 재생성(최대 2회) 후 종료.
6. **`trace`는 `GraphState`에 필드를 추가하지 않는다.** `graph.get_state_history(config)`로 노드별 스냅샷(타이밍/재시도횟수/인터럽트 여부)을 그대로 얻고, 세부 진행 이벤트는 rag-practice의 `get_stream_writer()` 패턴을 그대로 가져와 run별 인메모리 버퍼에 쌓는다 (프로세스 생존 중에만 유효 — 명확히 알려진 트레이드오프).
7. **`GET /runs/{id}`는 1차로 폴링만 지원**하고 SSE는 보류 — `POST /runs`가 동기 호출이라 완료된 호출을 나중에 스트림으로 재구성할 수 없기 때문. 실시간 스트리밍이 꼭 필요해지면 `POST /runs`/`resume` 자체를 SSE로 바꾸는 별도 작업으로 분리.
8. **`GraphState` 확장**: 스펙 3.2의 필드에 `difficulty: str`(easy/medium/hard), `query_type: str`(aggregate/list/cohort) 두 필드를 추가한다 — 이 둘은 조건부 엣지(모델 라우팅, 서브에이전트 분기)가 읽어야 하므로 trace/토큰과 달리 state 안에 있어야 함. 토큰 사용량은 trace와 동일하게 state 밖(`observability/cost_tracker.py`)에서 run_id 기준으로 추적한다.

---

## 6. 구현 순서 — 기능 단위, 수직 슬라이스 (백엔드+프론트엔드 동시 진행)

번호(0~13)는 실제 착수 순서, 알파벳(A~I)은 기능 그룹이다. **각 그룹은 백엔드와 프론트엔드를 함께 묶는다** — 그룹이 끝나면 그 기능은 화면에서 눈으로 확인 가능한 상태가 된다. 그룹 간에는 의존관계가 있는 것만 화살표로 표시.

```
0. 프레임워크 기본 세팅 (server FastAPI / client Vite+React+TS) — 선행, 1회성
        │
        ▼
A. 데이터 계층 ──▶ B. 코어 파이프라인 ──▶ C. Human-in-the-loop
 (프론트 없음)      (백+최소 프론트)         (백+프론트: 검토 화면 — 핵심 슬라이스)
                              │                              │
                              ├──▶ D. 비용/관측성 ────────────┤
                              │    (백+프론트: CostDashboard)  │
                              ├──▶ E. 멀티에이전트 ───────────┤
                              │    (백+프론트: 뱃지 표시)       │
                              └──▶ F. MCP 노출 ────────────────┘
                                   (백엔드만)                  ▼
                                                          H. 평가
                                                          (백+프론트: GoldenSetPanel)
                                                               │
                                                               ▼
                                                     I. Stretch goal
```

### 0. 프레임워크 기본 세팅 (선행)
`server/`에 FastAPI, `client/`에 Vite+React+TS 최소 골격만 세팅 — health check 엔드포인트와 기본 페이지가 뜨는 수준. 이후 모든 그룹이 여기 위에 기능을 얹는다.

### A. 데이터 계층
**실제 데이터셋과 스키마는 사용자가 별도로 제공한다.** 우리 역할은 접속 정보만 주면 어떤 Postgres 스키마든 연결·introspection·RAG 구축이 되는 **범용 커넥터**를 만드는 것 — 도메인 팩에 스키마를 손으로 채워넣는 게 아니다. 원래 이 그룹은 "백엔드/데이터 전용, 프론트 없음"으로 스코프했으나, 구현 확인용으로 미리보기 화면을 하나 추가했다(아래 2b).
1a. **도메인 팩 로더 + 접속/introspection (완료, 스모크테스트 검증됨)**: `app/domain/loader.py`(`DOMAIN` 설정값 → 도메인별 Postgres 접속 설정/Qdrant 컬렉션명 해석), `app/sql/schema_provider.py`(`information_schema`+`pg_catalog`로 테이블/컬럼/코멘트/PK/FK introspection). 빈 Postgres 컨테이너에 임의 테이블 하나(코멘트+FK 포함)를 만들어 전체 경로(loader→schema_provider)가 실제로 동작하는지 확인 완료, 컨테이너는 검증 후 폐기
1b. **스키마 인덱서 (완료)**: `app/knowledge/schema_indexer.py` — `schema_provider`가 만든 테이블별 텍스트를 `app/embedding/embedder.py`(BAAI/bge-m3)로 임베딩해 Qdrant `schema_{domain}` 컬렉션에 색인. `poc_prostate` 도메인 16테이블 색인 완료, "전립선암 환자의 수술 이력을 알고 싶어" 질의로 유사도 검색 시 `poc_prostate_op`(수술 이력 마트)가 2위로 정확히 잡히는 것까지 확인 — "접속 정보만 주면 RAG 구축" 요구사항이 end-to-end로 검증됨
2. **실제 도메인 연결 — `poc_prostate` (완료)**: 사용자가 전달한 실제 PoC 데이터(전립선암 도메인 — rag-practice에서 이미 Postgres로 마이그레이션된 `poc` 스키마와 동일 도메인)로 첫 실제 도메인을 연결함.
   - `docker-compose.yml`의 `postgres` 서비스에 rag-practice `db/01~03_*.sql`(소스 12테이블 + 마트 4테이블 + 샘플데이터) 적용
   - 사용자가 준 데이터 딕셔너리(`POC 대상 테이블 정리.xlsx`, 16개 테이블·335개 컬럼)로 `COMMENT ON TABLE/COLUMN`을 생성해 DB에 직접 주입 — rag-practice의 원본 Postgres 마이그레이션엔 실제 DB 코멘트가 없었기 때문(소스코드 주석만 있었음)에 이 작업이 꼭 필요했음
   - `DOMAIN=poc_prostate`(`server/.env`)로 `scripts/test_connection.py` 실행 → 16테이블 전체 인식, 92컬럼 마트 테이블 코멘트까지 정상 확인
   - 아직 안 한 것: few-shot 예제(`few_shot.json`)·골든셋(`golden_set.json`)은 여전히 사람이 작성해야 함. 사용자가 함께 준 코드/값 룩업 3종(PSA 처방코드, PSA 위험군 분류, Gleason Score 위험군 분류, 원발부위-조직진단 맵핑)은 `value_anchor.py`/`schema_explorer` 계열 작업에서 도메인 용어→코드값 매핑에 쓸 수 있는 소스로 확보됨 — 아직 반영은 안 함

2b. **[화면] 도메인 & 스키마 탐색기 미리보기 (완료)**: A 그룹 전체(연결·introspection·RAG 검색)를 눈으로 확인하기 위한 화면. B로 넘어가기 전, "질의 실행" 화면과는 별개로 먼저 만듦.
   - **[백엔드]** `app/api/domain_routes.py` — `GET /domain/status`, `GET /domain/tables`, `GET /domain/tables/{table}`, `GET /domain/schema-search?q=` 4개 신규 엔드포인트, `app/main.py`에 CORS(`localhost:5173`) 설정. 전부 curl로 정상 응답 확인
   - **[프론트]** `client/src/App.tsx` — 상태 바 + 테이블 목록 + 스키마 시맨틱 검색 + 테이블 상세(컬럼/PK/FK) 4존 레이아웃. 디자인 토큰은 기존 "질의 실행" 프로토타입 것을 그대로 재사용(`client/src/styles/tokens.css`)
   - **디자인 브리프**: 이 화면의 상세 스펙 + 전체 화면 지도(질의 실행/도메인 탐색기/실행 히스토리/Golden Set 평가/검토 정책/비용 대시보드)를 디자이너 전달용 문서로 별도 작성 — `docs/screen-spec.html`, Artifact로도 발행함
   - 검증: 백엔드 4개 엔드포인트 curl 확인 + CORS 헤더 확인 + `npm run build` 무오류 + dev 서버 기동까지 확인. **브라우저 렌더링 자체는 육안으로 확인 못함** — 스크린샷/브라우저 자동화 도구가 세션에 없어서, 실제 레이아웃·인터랙션 확인은 사용자가 `http://localhost:5173`에서 직접 해야 함

### B. 코어 파이프라인 (자동 모드, interrupt 없음)
사람 개입 없이 질의→SQL→실행까지 전 구간이 도는 최소 골격 + 그 결과를 화면에서 확인할 수 있는 최소 프론트.
3. **[백엔드] LangGraph 골격**: `app/graph/state.py`(difficulty/query_type 포함), `nodes/intent.py`(난이도 태그 포함), `nodes/*.py`(review 노드는 항상 auto-pass로), `app/graph/build.py`, `app/sql/*`(A/B 카테고리 파일 이관), `app/llm/base.py`(토큰 카운팅 래퍼 내장), `app/llm/gemini_client.py`, `app/embedding/embedder.py` — **Tier1 두 항목(토큰 계측, 난이도 태그)을 이 단계에서 거의 공짜로 흡수**
3b. **[프론트] 최소 결과 화면**: `QueryCard.tsx` + 자동모드 실행 결과(SQL/결과 표) 표시만 하는 화면 — 이 시점엔 `/runs`가 아직 없으므로 CLI로 돌린 결과를 붙여보는 수준으로도 충분
4. **[백엔드] Golden set + Execution Accuracy**: `domains/<domain>/golden_set.json`(실제 데이터셋 확정 후 작성), `eval/execution_accuracy.py`
5. **[백엔드] Validation + self-correction 재시도 루프**: `nodes/validation.py`, `retry_count` 조건부 엣지 추가

### C. Human-in-the-loop (핵심 슬라이스)
스펙의 핵심 요구사항. 프로토타입 UI의 검토/승인 인터랙션이 여기서 처음 실제로 동작한다.
6. **[백엔드] Interrupt/resume 추가**: `nodes/schema_review.py`, `nodes/sql_review.py`, PostgresSaver 연결, `app/runs/run_manager.py`
7. **[백엔드] FastAPI 엔드포인트**: `app/api/routes.py` (4개 엔드포인트, 섹션 5의 핸들러 설계 그대로)
7b. **[프론트] 검토 화면**: `StageRail.tsx`, `SchemaLinkingStage.tsx`(후보 체크박스+승인), `SqlGenerationStage.tsx`(SQL 편집+승인), `SchemaGraph.tsx`, `state/useRunStore.ts`, `api/runsClient.ts` — 섹션 4 매핑표대로 프로토타입 인터랙션을 그대로 이식, `/runs` API에 실제 연동

### D. 비용/관측성 (Tier1)
B의 토큰 계측 훅에 라우팅 로직만 얹으면 되므로, C와 독립적으로 바로 이어서 진행 가능.
8. **[백엔드] 난이도별 모델 라우팅 마무리**: `app/llm/router.py`(easy→저비용, hard→고성능 모델 분기), `observability/cost_tracker.py` 완성
8b. **[프론트] `CostDashboard.tsx`**: run별 토큰 사용량, 스키마 검색 도입 전/후 비교, 난이도별 모델 분기 현황

### E. 멀티에이전트 확장 (Tier2)
B의 그래프 골격에 노드만 추가하는 구조라 C·D와 독립적으로 진행 가능.
9. **[백엔드] 멀티에이전트 승격**: `nodes/intent.py`에 질의유형 분류 추가, `nodes/sql_generation/{aggregate,list,cohort}.py`로 분리(유형별 전문 프롬프트·도구)
9b. **[프론트] 질의유형 뱃지**: `StageRail.tsx`의 intent 스테이지에 질의유형(집계/리스트/코호트) 표시만 추가 — 별도 화면 불필요

### F. MCP 노출 (Tier2, 백엔드만)
C의 FastAPI 도구 함수가 있어야 래핑할 대상이 생기므로 C 완료 후. 외부 클라이언트용이라 자체 프론트 화면 불필요.

**전송 방식**: 별도 stdio 프로세스가 아니라 **기존 FastAPI 프로세스에 서브마운트**한다 — `mcp.streamable_http_app()`을 `app.main`에서 `/mcp`로 `app.mount()`. `_graph_cache`/embedder 싱글톤을 그대로 재사용할 수 있고 프로세스 관리가 늘지 않는다는 게 이유. 구현 시 주의점: `FastMCP`의 streamable-http 앱은 자체 lifespan(세션 매니저)이 있어서, 부모 `FastAPI(lifespan=...)`에 그 lifespan을 같이 걸어주지 않으면 `/mcp` 요청이 걸려있게 된다.

**노출 tool (5개)** — 전부 읽기이거나 이미 검증된 실행 경로만 래핑한다:

| tool | 재사용 대상 | 비고 |
|---|---|---|
| `get_domain_status()` | `domain_routes.domain_status` | 그대로 |
| `list_tables()` | `domain_routes.list_tables` | 그대로 |
| `get_table_detail(table_name)` | `domain_routes.table_detail` | 그대로 |
| `search_schema(query, limit=5)` | `domain_routes.schema_search` | 그대로 |
| `search_few_shot_examples(question, top_k=3, domain=None)` | `SqlRetriever` + `QdrantFewShotStore` | REST엔 없던 신규 조합 — `query_tables=[]`로 호출해 semantic+domain 스코어만 사용 |
| `run_nl2sql_query(question, domain=None)` | `run_routes` 내부 실행 로직(아래 참고) | MCP에서는 `review_config`를 항상 `{"schema": False, "sql": False}`로 고정 — 단발 tool 호출로는 interrupt/resume을 받을 수 없어 애초에 자동 모드만 지원 |

**의도적으로 뺀 것 — "SQL 직접 실행" tool**: 스펙 전체가 "검증 게이트(SqlValidator/schema citation/value anchor)를 통과한 SQL만 실행"인 구조인데, raw SQL을 MCP에 노출하면 그 게이트를 완전히 우회하는 구멍이 생긴다. `run_nl2sql_query`가 질문→(내부적으로 스키마링킹/생성/검증/실행 전체 파이프라인)→결과를 돌려주는 유일한 실행 경로다.

**작은 리팩터링 필요**: `run_routes.create_run`은 지금 "도메인 resolve → graph 호출 → `_finalize`"가 한 함수 안에 있어 HTTP 계층과 분리돼 있지 않다. MCP tool에서 이 로직을 중복 작성하지 않도록 `execute_run(question, domain_name, review_config, tags) -> dict`를 추출해 `create_run`(HTTP)과 MCP tool이 함께 호출하도록 한다 (동작 변경 없는 순수 리팩터링).

**파일 변경**: `server/requirements.txt`(`mcp` 추가), `server/app/api/mcp.py`(신규 — `FastMCP` 인스턴스 + tool 5개), `server/app/api/run_routes.py`(`execute_run` 추출), `server/app/main.py`(`/mcp` 서브마운트 + lifespan 배선).

10. **MCP 서버 노출 (완료)**: `app/api/mcp.py`(`MCPServer` + tool 6개 — `get_domain_status`/`list_tables`/`get_table_detail`/`search_schema`/`search_few_shot_examples`/`run_nl2sql_query`), `run_routes.py`에서 `execute_run()` 추출, `main.py`에서 `/mcp` 서브마운트 + lifespan 배선. mcp 파이썬 SDK가 2.x에서 `FastMCP`→`MCPServer`로 개명되고 클라이언트 헬퍼도 `streamablehttp_client`→`streamable_http_client`로 바뀌어 있었음(설치된 `mcp==2.1.1` 기준으로 반영). 실제 `mcp` 클라이언트(`streamable_http_client`+`ClientSession`)로 로컬 uvicorn(`/mcp`)에 접속해 6개 tool 전체 호출 검증 완료 — `list_tables`/`get_domain_status`/`search_schema`/`get_table_detail`은 활성 도메인(`poc_prostate`)에서 정상 응답, `search_few_shot_examples`는 유사 예제 검색 확인, `run_nl2sql_query`("전립선암 환자는 총 몇 명인가요?")는 스키마링킹→SQL생성→검증→실행 전 과정을 거쳐 정답(8명)까지 확인. `execute_run` 추출 후 기존 REST `POST /runs`도 동일 응답으로 회귀 없음 확인.

### H. 평가
D·E·G가 만든 지표/화면을 모두 사용하므로 마지막.
12. **[백엔드] 평가 지표 전체 재측정**: `eval/condition_summary_faithfulness.py`, `eval/schema_mapping_accuracy.py`, `eval/self_correction_ablation.py`(retry on/off), `eval/token_cost_comparison.py`(전체 스키마 덤프 vs Qdrant 검색 토큰 비교, 난이도 라우팅 on/off 비용-정확도 트레이드오프)
12b. **[프론트] `GoldenSetPanel.tsx`**: 난이도별 정확도 바 — eval 스크립트 결과를 반환하는 엔드포인트/정적 JSON 연동

### I. Stretch goal (8주 스코프 밖)
13. **교정 사례 학습 루프** — 사용자가 승인/수정한 스키마·SQL을 few-shot 저장소에 재투입하는 RAG 기반 축적 루프

RBAC은 별도 구현 단계 없음 — 필요 시 `client`에 역할 선택 드롭다운만 추가하는 목업으로 처리하거나 발표 자료에 "Out of Scope, 설계만 언급"으로 명시.

---

## 7. 검증 방법

- 0단계 후: `uvicorn app.main:app`로 FastAPI `/health` 응답 확인, `npm run dev`로 Vite 기본 페이지 확인
- 1a단계 후 (완료): 빈 Postgres 컨테이너 + 임의 테이블 하나(코멘트·FK 포함)로 `scripts/test_connection.py --domain smoketest` 실행 → 연결 성공, 테이블 목록, 코멘트·PK·FK가 텍스트로 정확히 나오는 것 확인. 컨테이너/임시 도메인 디렉토리는 검증 후 삭제
- 1b단계 후 (완료): `python app/knowledge/schema_indexer.py --domain poc_prostate` 실행 → `schema_poc_prostate` 컬렉션에 16개 테이블 색인 확인, 실제 자연어 질의("전립선암 환자의 수술 이력을 알고 싶어")로 `query_points()` 호출해 관련 테이블이 상위로 검색되는지까지 확인
- 2단계 후 (실제 데이터 도착 시): `.env`에 실제 접속 정보 채우고 `scripts/test_connection.py --domain <실제도메인>`으로 연결·introspection 확인 → `scripts/seed_few_shot.py --domain <실제도메인>` 실행 후 `sql_knowledge_{domain}` 컬렉션에 few-shot 예제 수 확인
- 3단계 후: CLI 스크립트로 `graph.invoke()` 직접 호출해 자동 모드 전체 파이프라인이 SQL 실행까지 끝까지 도는지, `difficulty`/토큰 카운트가 state·로그에 정상 기록되는지 확인
- 3b단계 후: 3단계 CLI 실행 결과를 최소 화면에 붙여 SQL/결과 표가 정상 렌더링되는지 눈으로 확인
- 4단계 후: golden set 스크립트 실행해 baseline Execution Accuracy 수치 확보
- 6~7b단계 후: React 화면에서 실제로 질의 실행 → 스키마 후보 검토/체크 해제 → 승인 → SQL 검토/수정 → 승인 → 결과 확인까지 end-to-end로 수동 테스트 (프로토타입 HTML과 나란히 놓고 동일 시나리오 시각적/기능적 비교)
- 8~8b단계 후: golden set을 난이도 라우팅 on/off로 각각 돌려 비용/정확도 차이 확보하고 `CostDashboard`에 반영되는지 확인
- 9~9b단계 후: 질의유형별(집계/리스트/코호트) 골든셋 서브셋으로 서브에이전트 분기가 올바르게 타는지, `StageRail`에 뱃지가 표시되는지 확인
- 10단계 후 (완료): `uvicorn app.main:app` 기동 → mcp 파이썬 클라이언트(`streamable_http_client`+`ClientSession`)로 `http://localhost:8000/mcp` 접속 → `list_tools()`로 6개 tool 노출 확인, 6개 전체 개별 호출해 REST 대응 엔드포인트와 같은 필드 구조로 응답하는지 확인, `run_nl2sql_query`는 실제 SQL 실행까지 end-to-end 확인. `execute_run` 추출 후 `POST /runs`가 기존과 동일하게 동작하는지 별도 확인
- 12~12b단계 후: 토큰 비교/비용-정확도 실험 결과를 `GoldenSetPanel`/표·그래프로 정리해 발표 자료용 수치 확보
