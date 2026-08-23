# Data Access Copilot — master-project 이관/구축 계획

## Context

`master-project`에는 현재 UI 프로토타입 HTML(`data-access-copilot-prototype.html`) 한 개만 있고 `server`/`client` 디렉토리는 아직 없다. 목표는 이 프로토타입을 목표 UI로 삼아, 첨부된 "Data Access Copilot" 구현 스펙(LangGraph 기반 NL2SQL + schema/SQL 두 지점 human-in-the-loop)을 새로 구축하는 것이다.

기존 `rag-practice/server/sqlgen`에 이미 동작하는 NL2SQL 구현이 있지만, 두 차례의 코드 탐색으로 확인한 결과:
- **Postgres/pgvector 전제**인 부분(스키마 조회, few-shot 저장소)이 많아 스펙이 요구하는 **SQLite + Qdrant**로 가려면 DB 계층을 다시 써야 한다.
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

### A. 거의 그대로 복사 (도메인/DB 비의존)
| 원본 | 대상 | 비고 |
|---|---|---|
| `server/docrag/dense_embedder.py`의 `EmbeddingEngine` | `server/app/embedding/embedder.py` | BAAI/bge-m3, 한국어 지원, 완전 범용 — 그대로 복사 |
| `server/sqlgen/canonicalizer.py` | `server/app/sql/canonicalizer.py` | `dialect` 파라미터만 `"sqlite"`로 |
| `server/sqlgen/validator.py` | `server/app/sql/validator.py` | SELECT-only 검사, `dialect="sqlite"`로 변경 |

### B. 로직 재사용, DB 계층만 재작성 (SQLite 대응)
| 원본 | 대상 | 변경 사항 |
|---|---|---|
| `server/sqlgen/value_anchor.py` | `server/app/sql/value_anchor.py` | 리터럴 추출 로직 유지, `psycopg2 %s`→`sqlite3 ?`, 코드컬럼 휴리스틱(`_cd`/`_nm`)은 새 스키마에 맞게 재정의 |
| `server/sqlgen/schema_citation_validator.py` | `server/app/sql/schema_citation_validator.py` | alias/CTE 해석 로직 유지, `information_schema` 조회 → `PRAGMA table_info` 기반으로 교체 |
| `server/sqlgen/retriever.py` | `server/app/sql/retriever.py` | 하이브리드 스코어링(0.5 semantic+0.3 table jaccard+0.2 domain) 로직 유지, 저장소만 Qdrant로 교체 |
| `db/05_seed_sql_knowledge.py` | `server/scripts/seed_few_shot.py` | question/intent/sql/tables/metrics/domain 필드 구조 유지, 저장소를 Qdrant 컬렉션(`sql_knowledge_{domain}`)으로 교체, `--domain` 인자로 도메인 팩의 `few_shot.json`을 읽도록 일반화 |
| `db/04_apply_schema.py` | `server/scripts/apply_schema.py` | "SQL 파일 순서대로 실행 + row count 검증" 패턴 유지, sqlite3 기반으로, `--domain` 인자로 도메인 팩의 `ddl.sql`을 읽도록 일반화 |
| `server/generation/llm_client.py` | `server/app/llm/gemini_client.py` (+ `base.py` 인터페이스) | 캐싱 패턴은 재사용, `generate/generate_stream` 인터페이스로 감싸 vLLM 교체 가능하게 |

### C. 패턴만 참고, 내용은 새로 작성
- `server/sqlgen/schema_provider.py` → 새 `schema_provider.py`: Postgres `information_schema` 대신 **정적 YAML 메타데이터 + `sqlite3 PRAGMA`** 조합으로 재작성. 단 YAML 경로를 하드코딩하지 않고 `DOMAIN` 설정값으로 `server/domains/<domain>/schema.yaml`을 로드하도록 파라미터화 — 도메인 교체 시 코드 변경 없이 설정값만 바꾸면 됨 (아래 "도메인 팩" 설계 참고)
- `server/sqlgen/schema_explorer.py` → 개념(키워드검색→FK추적→값샘플링)만 참고, 코드는 새 `schema_linking_node`가 대체(Qdrant 유사도 검색 + LLM 최종 선정으로 단순화 — FK 2-hop 추적 같은 복잡한 휴리스틱은 1차 구현에서 제외)
- `server/sqlgen/prompt_builder.py` → 구조적 패턴(시스템+스키마+예제+재시도 피드백 블록, `VALUE_UNCONFIRMED` 탈출구)은 공통 템플릿으로 유지하되, 도메인 특화 문구(할루시네이션 블록리스트, 도메인 용어 등)는 Python 코드에 박지 않고 도메인 팩의 `prompt_fragments.yaml`에서 읽어와 템플릿에 주입 — 새 도메인 추가 시 이 YAML만 새로 작성하면 됨
- `server/sqlgen/pipeline.py`, `server/service/ask_service.py`, `server/retrieval/router.py` → 노드 책임 분리 참고용, 실제로는 LangGraph 그래프가 대체
- `ui/tabs/sqlgen/debug_sql.py`의 스테이지/attempts 렌더링 → `GET /runs/{id}/trace` 응답 설계 및 React 스테이지 레일 참고
- `server/chatgraph/graph.py`, `server/api/dependencies.py`, `server/api/routes/chat_session.py` → **LangGraph 배선 방식(체크포인터 생성, `thread_id` 매핑, `get_stream_writer()` 커스텀 이벤트)**의 실제 동작 예시로 직접 참고

### D. 완전 신규
- **도메인 팩 로더 (엔진 쪽 이음새, 재사용성의 핵심)**: `DOMAIN` 설정값 → 도메인 팩 경로 해석, Qdrant 컬렉션명 파라미터화(`sql_knowledge_{domain}`). 이 로더가 있어야 나중에 다른 도메인을 "코드 변경 없이 팩 추가 + 설정값 변경"만으로 붙일 수 있음
- `db/01~03_*.sql` (전립선암 마트) → 재사용 불가. 새 데이터셋은 **도메인 팩 구조**로 제작: `server/domains/clinical_v1/{schema.yaml, ddl.sql, synthetic_data.py, few_shot.json, golden_set.json, prompt_fragments.yaml}`. `patients, diagnoses, encounters, departments, medications, lab_results, physicians, appointments` 8개 테이블 + 유사 컬럼명 의도적 중복·의료 약어·1:N 관계는 이 팩 안에 위치. 합성데이터 생성기는 1차로 도메인 팩 내부의 도메인 특화 스크립트로 두고, 범용화(faker 기반 스키마-드리븐 생성기)는 필요 시 후속 작업으로 미룬다 — 지금은 이음새만 확보하고 실제로 두 번째 도메인까지 만들지는 않음
- Golden query set (25~30개, Easy/Medium/Hard) — `domains/clinical_v1/golden_set.json`으로 신규 작성
- LangGraph 그래프/노드, FastAPI `/runs` 엔드포인트, React 프론트엔드 — 전부 신규

---

## 3. 디렉토리 구조

```
master-project/
├── data-access-copilot-prototype.html   (유지 — 디자인 레퍼런스)
├── docker-compose.yml                    (Qdrant 단일 서비스만; Postgres 불필요)
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
│   │   │   ├── schema_provider.py    # DOMAIN 설정값으로 domains/<domain>/schema.yaml 로드
│   │   │   └── prompt_builder.py     # 공통 템플릿 + domains/<domain>/prompt_fragments.yaml 주입
│   │   ├── llm/
│   │   │   ├── base.py              # 인터페이스 + 토큰 카운팅 래퍼(Tier1, 모든 generate() 호출 계측)
│   │   │   ├── gemini_client.py
│   │   │   └── router.py            # 난이도별 모델 라우팅 (Tier1)
│   │   ├── embedding/embedder.py
│   │   ├── knowledge/qdrant_store.py     # few-shot 저장소 (Qdrant), 컬렉션명 = sql_knowledge_{domain}
│   │   ├── db/sqlite_client.py
│   │   ├── domain/loader.py              # DOMAIN 설정값 → 도메인 팩 경로/Qdrant 컬렉션명 해석 (재사용성 이음새)
│   │   ├── observability/cost_tracker.py # run별 토큰/비용 인메모리 버퍼 (trace와 동일한 방식으로 state 밖에서 추적)
│   │   └── runs/run_manager.py           # run_id 존재확인 registry + 상태 파생 헬퍼
│   ├── domains/
│   │   └── clinical_v1/              # 도메인 팩 — 새 도메인 추가 시 이 디렉토리 형태를 복제
│   │       ├── schema.yaml
│   │       ├── ddl.sql
│   │       ├── synthetic_data.py     # 도메인 특화 합성데이터 생성 스크립트
│   │       ├── few_shot.json
│   │       ├── golden_set.json
│   │       └── prompt_fragments.yaml
│   ├── scripts/
│   │   ├── apply_schema.py       # --domain 인자로 해당 팩의 ddl.sql 적용 + row count 검증
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
2. **체크포인터는 SqliteSaver 사용** (`langgraph.checkpoint.sqlite`). rag-practice는 Postgres 체크포인터를 쓰지만, 이 프로젝트는 스펙 전반이 SQLite 우선이고 단일 프로세스(uvicorn 단일 워커) 전제이므로 Postgres를 새로 끌어올 필요가 없다. MemorySaver는 프로세스 재시작 시 검토 대기 중인 run이 전부 사라지므로 배제.
3. **`run_id` = `thread_id`** (`f"nl2sql-{run_id}"` 네임스페이스만 접두). 별도 매핑 테이블 불필요하나, "존재하지 않는 run"과 "빈 상태"를 구분하기 위한 최소 `runs` registry(run_id, created_at, review_config, status_cache)는 필요.
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

### A. 데이터 계층 (백엔드/데이터 전용, 프론트 없음)
재사용을 위한 **도메인 팩 이음새(엔진)를 먼저 만들고**, 그 다음 실제 구현할 도메인 하나(`clinical_v1`)를 채운다 — 순서를 바꾸면(팩부터 채우고 나중에 파라미터화) 하드코딩이 먼저 자리잡아 되돌리는 비용이 더 크다.
1a. **도메인 팩 로더 (엔진 이음새)**: `app/domain/loader.py`(`DOMAIN` 설정값 → 팩 경로/Qdrant 컬렉션명 해석), `app/sql/schema_provider.py`·`app/sql/prompt_builder.py`를 하드코딩 경로 대신 loader 경유로 파라미터화, `scripts/apply_schema.py`·`scripts/seed_few_shot.py`를 `--domain` 인자를 받는 범용 스크립트로 작성. 이 시점엔 아직 채울 도메인 팩이 없으므로 빈 스키마/더미 데이터로 동작만 검증
1b. **`clinical_v1` 도메인 팩 채우기**: `server/domains/clinical_v1/schema.yaml`, `ddl.sql`(8테이블 DDL), `synthetic_data.py`(1:N 관계·유사 컬럼명·의료약어 포함 합성데이터), `prompt_fragments.yaml` — 1a에서 만든 loader/스크립트로 바로 적용되는지 확인
2. **Qdrant 인덱싱**: `docker-compose.yml`(Qdrant), `app/knowledge/qdrant_store.py`(컬렉션명 = `sql_knowledge_{domain}`), `scripts/seed_few_shot.py --domain clinical_v1`로 `domains/clinical_v1/few_shot.json` 최초 시딩

### B. 코어 파이프라인 (자동 모드, interrupt 없음)
사람 개입 없이 질의→SQL→실행까지 전 구간이 도는 최소 골격 + 그 결과를 화면에서 확인할 수 있는 최소 프론트.
3. **[백엔드] LangGraph 골격**: `app/graph/state.py`(difficulty/query_type 포함), `nodes/intent.py`(난이도 태그 포함), `nodes/*.py`(review 노드는 항상 auto-pass로), `app/graph/build.py`, `app/sql/*`(A/B 카테고리 파일 이관), `app/llm/base.py`(토큰 카운팅 래퍼 내장), `app/llm/gemini_client.py`, `app/embedding/embedder.py` — **Tier1 두 항목(토큰 계측, 난이도 태그)을 이 단계에서 거의 공짜로 흡수**
3b. **[프론트] 최소 결과 화면**: `QueryCard.tsx` + 자동모드 실행 결과(SQL/결과 표) 표시만 하는 화면 — 이 시점엔 `/runs`가 아직 없으므로 CLI로 돌린 결과를 붙여보는 수준으로도 충분
4. **[백엔드] Golden set + Execution Accuracy**: `domains/clinical_v1/golden_set.json`, `eval/execution_accuracy.py`
5. **[백엔드] Validation + self-correction 재시도 루프**: `nodes/validation.py`, `retry_count` 조건부 엣지 추가

### C. Human-in-the-loop (핵심 슬라이스)
스펙의 핵심 요구사항. 프로토타입 UI의 검토/승인 인터랙션이 여기서 처음 실제로 동작한다.
6. **[백엔드] Interrupt/resume 추가**: `nodes/schema_review.py`, `nodes/sql_review.py`, SqliteSaver 연결, `app/runs/run_manager.py`
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
10. **MCP 서버 노출**: `app/api/mcp.py` — 기존 FastAPI 도구 함수(스키마 조회/SQL 실행/few-shot 검색 등)를 MCP tool로 래핑

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
- 1a단계 후: `DOMAIN` 값을 바꿔가며 `loader.py`가 존재하지 않는 도메인엔 명확한 에러를, 더미 팩엔 정상 경로를 반환하는지 확인 — 아직 실데이터 없이 배선만 검증
- 1b단계 후: `scripts/apply_schema.py --domain clinical_v1` 실행 후 `sqlite3 clinical_v1.db ".tables"`로 8테이블 생성 확인, 로우 카운트 점검
- 2단계 후: `scripts/seed_few_shot.py --domain clinical_v1` 실행 후 `sql_knowledge_clinical_v1` 컬렉션에 few-shot 예제 수 확인 (`curl localhost:6333/collections/...`)
- 3단계 후: CLI 스크립트로 `graph.invoke()` 직접 호출해 자동 모드 전체 파이프라인이 SQL 실행까지 끝까지 도는지, `difficulty`/토큰 카운트가 state·로그에 정상 기록되는지 확인
- 3b단계 후: 3단계 CLI 실행 결과를 최소 화면에 붙여 SQL/결과 표가 정상 렌더링되는지 눈으로 확인
- 4단계 후: golden set 스크립트 실행해 baseline Execution Accuracy 수치 확보
- 6~7b단계 후: React 화면에서 실제로 질의 실행 → 스키마 후보 검토/체크 해제 → 승인 → SQL 검토/수정 → 승인 → 결과 확인까지 end-to-end로 수동 테스트 (프로토타입 HTML과 나란히 놓고 동일 시나리오 시각적/기능적 비교)
- 8~8b단계 후: golden set을 난이도 라우팅 on/off로 각각 돌려 비용/정확도 차이 확보하고 `CostDashboard`에 반영되는지 확인
- 9~9b단계 후: 질의유형별(집계/리스트/코호트) 골든셋 서브셋으로 서브에이전트 분기가 올바르게 타는지, `StageRail`에 뱃지가 표시되는지 확인
- 10단계 후: MCP 클라이언트(예: `mcp inspector` 또는 Claude Desktop)로 노출된 tool 호출 테스트
- 12~12b단계 후: 토큰 비교/비용-정확도 실험 결과를 `GoldenSetPanel`/표·그래프로 정리해 발표 자료용 수치 확보
