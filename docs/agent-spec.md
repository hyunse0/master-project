# Data Access Copilot — Agent 명세서

> B단계(코어 파이프라인 + KPI 인프라)·C단계(human-in-the-loop) 구현 완료 시점(2026-08-25) 기준으로,
> `server/app/` 실제 코드를 근거로 작성했다. 각 항목 옆에 근거 파일을 명시한다.

## 1. Agent 페르소나 및 시스템 프롬프트 (Identity)

| 항목 | 정의 내용 |
| --- | --- |
| **Agent 이름** | Data Access Copilot (`README.md`) |
| **주요 역할** | 자연어 질문을 스키마 링킹 → SQL 생성 → 검증 → 실행 4단계 파이프라인으로 처리하는 NL2SQL 에이전트. 접속 정보만 주면 임의의 Postgres 스키마를 대상으로 동작하는 범용 커넥터(`app/domain/loader.py`) 위에서, 현재는 임상 데이터 도메인(`poc_prostate`)을 대상으로 동작 |
| **핵심 목표** | ① 스키마 인용 정확성 — 존재하지 않는 컬럼을 근거로 SQL을 만드는 환각 방지(`schema_citation_validator.py`) ② 값 anchoring — WHERE절 리터럴이 실제 DB에 존재하는 값인지 검증(`value_anchor.py`) ③ 읽기 전용 안전성 — 단일 SELECT만 허용(`validator.py`) ④ 스키마/SQL 두 지점에서 사람이 실제로 멈춰서 검토·승인할 수 있는 human-in-the-loop |
| **톤앤매너** | 시스템 프롬프트가 "PostgreSQL SELECT 쿼리 작성 전문가" 페르소나로 고정(`prompt_builder.py`). 자유서술이 아니라 **의도 / SchemaCitation / SQL** 3블록 고정 출력 형식을 강제하고, "컬럼명이 의미를 보장한다고 절대 가정하지 마세요"처럼 근거 없는 추측을 명시적으로 금지하는 단정적·규정적 톤 |
| **제약 사항** | DDL/DML/멀티문 금지(SELECT만, CTE 허용) · 스키마에 없는 테이블/컬럼 사용 금지 · PostgreSQL 미지원 문법(SYSDATE/NVL/ROWNUM/QUALIFY 등) 금지 · 값이 [값 위치]에 `found=true`로 없으면 SQL 작성 대신 `VALUE_UNCONFIRMED`로 반려 · **review_config.sql이 켜진 상태에서 검증/실행이 실패해도 sql_generation으로 자동 재생성하지 않고 반드시 sql_review(사람)로 돌아감** — 사람이 이미 승인한 SQL을 몰래 덮어쓰지 않기 위한 설계상 제약(`build.py` 주석) |

## 2. 워크플로우 및 오케스트레이션 (Workflow & Logic)

### 2.1 처리 로직

* **Step 1 (Input Analysis)** — `intent_node`(`app/graph/nodes/intent.py`)가 LLM 1회 호출로 질문을 JSON 분류: `task_type`(count/sum/avg/list/trend/…), `metric`, `dimensions`, `time_range`, `difficulty`(easy/medium/hard). 파싱 실패 시 안전한 기본값으로 폴백하며 `intent_status`/`intent_error`에 성공 여부를 남긴다. (`table_hints`/`schema_hints`로 스키마 링킹 검색어를 보강하는 시도는 EXP-002에서 효과가 없어 폐기 — `docs/kpi-experiment-log.md` 참고)
* **Step 2 (Tool Selection & 분기)**
  * `schema_linking_node` — 질문 임베딩으로 Qdrant `schema_{domain}` 컬렉션에서 top-5 테이블 검색. `tags["schema_rag_mode"]="full_dump"`면 검색을 건너뛰고 전체 스키마를 덤프(KPI 비교용 토글).
  * `schema_review_node` — `review_config.schema`가 켜져 있으면 `interrupt("review_schema")`로 실제 정지, 꺼져 있으면 LLM(저비용 고정 모델)이 `schema_candidates` 중 질문에 실제 필요한 테이블만 closed-set으로 재선정(`confirmed_schema`)하고, 그 결과로 `schema_text`(SQL 생성 프롬프트의 스키마 설명)도 다시 조립한다 — DB 재조회 없이 `schema_candidate_details[].text`(Qdrant에 이미 색인된 렌더링)로 조립하고, 후보 밖 테이블이 선택된 예외 상황에서만 DB로 폴백한다. 파싱 실패/빈 응답이면 후보 전체를 그대로 유지(fail-safe). EXP-005(단순 재선정)는 Execution Accuracy가 떨어져 폐기, EXP-006(컬럼 근거 강제 + recall 편향 프롬프트로 보강)이 Execution Accuracy 손실 없이 스키마 매핑 F1을 개선해 채택 — `docs/kpi-experiment-log.md` 참고.
  * `sql_generation_node` — few-shot 하이브리드 검색(`retriever.py`) + `prompt_builder.py`로 프롬프트 구성 → LLM 호출. `VALUE_UNCONFIRMED` 응답이면 재시도(최대 `max_retries`), 아니면 `sql_review`로 진행.
  * `sql_review_node` — `review_config.sql` 켜짐 시 `interrupt("review_sql")`.
  * `validation_node` — `SqlValidator`(sqlglot AST: SELECT-only + 허용 테이블) + 스키마 인용 검증 + 값 anchoring을 통과해야 `execution`으로 진행.
  * `execution_node` — 실제 DB 실행(`statement_timeout=30s`, LIMIT을 500행 이하로 안전하게 재조정), 결과 0건이면 코드컬럼 필터 재검, LLM으로 `## 요약` 합성.
  * 실패 시 라우팅은 `review_config.sql` 여부로 분기: 꺼져 있으면 `sql_generation`으로 자동 재시도(상한 도달 시 종료), 켜져 있으면 항상 `sql_review`로 되돌아가 사람이 직접 고치거나 재승인하게 함(`build.py`의 `_route_after_validation`/`_route_after_execution`).
* **Step 3 (Execution & Response)** — `graph.invoke()`가 다음 interrupt 지점 또는 그래프 종료까지 동기 블로킹하고, 그 시점 상태를 `POST /runs`/`POST /runs/{id}/resume` 응답으로 그대로 반환(`run_routes.py`). `status`는 `success | error | interrupted_schema | interrupted_sql` 중 하나로 `graph.get_state().next`를 보고 판별.

### 2.2 상태 관리

* **턴 관리**: 대화형 멀티턴이 아니라 **질문 1건 = run 1건**. `GraphState`(TypedDict, `app/graph/state.py`)가 입력(question/domain/tags/review_config)부터 각 노드 산출물(schema_candidates, sql, retry_count, rows, summary 등)까지 하나의 실행 상태를 담는다.
* **LangGraph Node/Edge 흐름**:
  ```
  START → intent → schema_linking → schema_review → sql_generation
  sql_generation --(VALUE_UNCONFIRMED, retry<max)--> sql_generation
  sql_generation --(sql 확보)--> sql_review → validation
  validation --(review_config.sql 켜짐, 실패)--> sql_review
  validation --(꺼짐, retry<max)--> sql_generation   validation --(통과)--> execution
  execution  --(review_config.sql 켜짐, 실패)--> sql_review
  execution  --(꺼짐, retry<max)--> sql_generation   execution --(성공/소진)--> END
  ```
* **영속성**: `PostgresSaver` 체크포인터(`app/graph/checkpointer.py`)가 `thread_id=f"nl2sql-{run_id}"` 단위로 그래프 실행 상태를 Postgres에 영구 저장 — 프로세스가 재시작돼도 interrupt 지점부터 재개 가능. `runs.state_snapshot`(app-db)은 매 invoke/resume 직후 응답 전체를 캐싱해 `GET /runs/{id}` 재조회 시 체크포인터를 다시 읽지 않도록 하는 별도의 빠른 조회 캐시(진행 중 폴링 용도 아님 — POST 자체가 블로킹 호출).

## 3. 도구(Tools) 및 함수 명세 (Capability)

| 도구명 (Function) | 기능 설명 | 입력 파라미터 | 출력 데이터 |
| --- | --- | --- | --- |
| `SqlValidator.validate` (`app/sql/validator.py`) | sqlglot AST로 SELECT 전용 여부 + 참조 테이블이 허용 목록 안인지 검사 | `sql: str` | `ValidationResult(ok: bool, errors: list[str])` |
| `validate_schema_citations` (`app/sql/schema_citation_validator.py`) | SQL이 인용한 모든 컬럼이 `information_schema`에 실재하는지 검증(alias/CTE/SELECT 별칭 해석 포함) | `sql: str, conn` | `CitationResult(ok, missing: list[str], feedback: str)` |
| `check_value_anchors` (`app/sql/value_anchor.py`) | WHERE절 리터럴 값이 실제 컬럼에 존재하는지 DB에 직접 조회해 확인, 없으면 실제 DISTINCT 값을 피드백으로 반환 | `sql: str, conn` | `AnchorResult(ok, anchors, feedback)` |
| `SqlRetriever.retrieve` (`app/sql/retriever.py`) | few-shot SQL 예제를 하이브리드 스코어(0.5×semantic+0.3×table jaccard+0.2×domain)로 검색 | `embedding, query_tables, query_domain, top_k` | `list[RetrievedExample]` |
| `SchemaProvider.get_schema_text` (`app/sql/schema_provider.py`) | `information_schema`+`pg_description`+FK로 테이블/컬럼/코멘트를 텍스트로 조합 | `target_tables: list[str] | None` | `schema_text: str` |
| `AzureOpenAIChatClient.generate_with_usage` (`app/llm/azure_openai_client.py`) | SK AI Talent Lab 게이트웨이(Azure OpenAI 호환)로 채팅 완성 호출, md5 캐시 | `prompt: str` | `(answer: str, input_tokens: int, output_tokens: int)` |
| `EmbeddingEngine.embed` / `embed_batch` (`app/embedding/embedder.py`) | 같은 게이트웨이의 `text-embedding-3-small`로 임베딩 | `text: str` / `texts: list[str]` | `list[float]` / `list[list[float]]` |
| `_execute` (`app/graph/nodes/execution.py`) | 대상 도메인 DB에 SQL 실행 — `statement_timeout=30s`, LIMIT을 안전하게 재조정 | `domain, sql, max_rows` | `(columns: list[str], rows: list[dict])` |
| `POST /runs` (`app/api/run_routes.py`) | 새 run 시작, interrupt 또는 종료까지 동기 실행 | `question, domain?, review_config?` | run 응답(status/schema_candidates/sql/rows/…) |
| `POST /runs/{id}/resume` | interrupt된 run 재개(`Command(resume=...)`) | `confirmed_schema` 또는 `sql` | 위와 동일 형식 |
| `GET /runs/{id}` / `GET /runs/{id}/trace` | 캐싱된 마지막 상태 재조회 / 체크포인트 히스토리 조회 | `run_id` | state_snapshot / step 목록 |

## 4. 지식 베이스 및 메모리 전략 (Context & Memory)

### 4.1 RAG (검색 증강 생성) 전략

* **참조 데이터 소스**: ① 스키마 지식 — 대상 Postgres의 `information_schema`/`pg_description`을 실시간 introspection해 Qdrant `schema_{domain}` 컬렉션에 색인(`app/knowledge/schema_indexer.py`) ② Few-shot SQL 지식 — 도메인 팩의 `few_shot.json`을 `scripts/seed_few_shot.py`로 시딩해 `sql_knowledge_{domain}` 컬렉션에 저장 ③ 도메인 참고사항 — `domains/<domain>/prompt_fragments.yaml`의 자유서술 노트를 프롬프트에 `[도메인 참고사항]` 섹션으로 주입(없으면 생략, 신규 도메인도 즉시 동작).
* **청킹(Chunking) 방식**: 스키마는 **테이블 단위 1청크**(테이블명+코멘트+컬럼 목록+PK/FK를 하나로 합쳐 임베딩) — "이 질문에 필요한 테이블 집합"을 찾는 게 목적이라 컬럼 단위로 쪼개지 않음. Few-shot은 예제 1건(question+intent+canonical_sql+tables+metrics) = 1청크.
* **임베딩 모델**: SK AI Talent Lab LLM 게이트웨이의 `text-embedding-3-small`(1536차원, Azure OpenAI 호환). 원래 계획은 로컬 `BAAI/bge-m3`(sentence-transformers)였으나 사내 게이트웨이 전환 요청으로 교체되며 로컬 torch 의존성을 완전히 제거함.
* **Vector DB**: Qdrant. 컬렉션명은 도메인별로 파라미터화(`schema_{domain}`, `sql_knowledge_{domain}`), COSINE distance. 임베딩 차원이 바뀌면(과거 1024→1536 전환 사례) `_ensure_collection()`이 자동으로 컬렉션을 지우고 재생성.
* **검색 전략**: 스키마는 순수 벡터 top-5. Few-shot은 벡터 top-20 후보를 뽑은 뒤 하이브리드 스코어(0.5×semantic + 0.3×table Jaccard + 0.2×domain 일치)로 top-3 재순위.
* **KPI 검증 인프라**: `tags["schema_rag_mode"]="rag"|"full_dump"` 토글로 스키마 RAG 검색 vs 전체 스키마 덤프를 A/B 비교 가능(`eval/token_cost_comparison.py`). 실측 결과 토큰 -45%(104,056→57,187), 성공률 동일(92.9%) — `docs/kpi-schema-rag-mode-ablation.md`.

### 4.2 대화 메모리 (Conversation History)

* **메모리 유형**: 멀티턴 대화 히스토리는 없음 — 질문 1건이 독립된 run 1건으로 실행됨. 대신 LangGraph `PostgresSaver` 체크포인터가 "대화 맥락"이 아니라 **"파이프라인 진행 상태"**(스키마 후보, 생성된 SQL, retry_count, 재시도 피드백 등)를 `thread_id=nl2sql-{run_id}` 단위로 유지 — interrupt에서 멈춘 뒤 사람이 승인/수정하면 그 상태 그대로 재개된다.
* **저장 전략**: 체크포인트는 세션 타임아웃 없이 Postgres에 영구 보존(재개될 때까지 무기한). `runs.state_snapshot`은 매 invoke/resume 직후 API 응답 전체를 캐싱해 재조회를 빠르게 하는 용도로, 체크포인터와 별개로 갱신됨. run/스레드는 질문마다 새로 생성되며 재사용되지 않음(`app/runs/run_manager.py`).

## 5. 핵심 에이전트 기술 스택

| 구분 | 선정 전략/기술 | 선정 사유 (논리적 근거) |
| --- | --- | --- |
| **LLM Model** | `gpt-4.1-mini` — SK AI Talent Lab 사내 LLM 게이트웨이(Azure OpenAI 호환, `AzureOpenAIChatClient`) | 외부 Gemini/OpenAI 직결이 아닌 사내망 게이트웨이 정책을 따라야 했고, mini급으로 비용·속도를 확보하되 `TokenCountingLLM` 래퍼로 노드별 토큰을 계측해 실비용을 추적 |
| **Agent Framework** | LangGraph (`StateGraph`) | `schema_review`/`sql_review` 두 지점에서 `interrupt()`/`Command(resume=...)`로 실제로 멈추고 재개해야 하는 human-in-the-loop 요구사항에 정확히 대응. 조건부 엣지(`_route_after_validation` 등)로 재시도/재검토 라우팅을 명시적 코드로 표현 |
| **Prompt Strategy** | 구조화 출력 강제(의도/SchemaCitation/SQL 3블록) + 에러코드별 맞춤 재시도 가이드(`_RETRY_GUIDE`) + few-shot 예제 주입 | 자유서술 생성 시 스키마 환각(존재하지 않는 컬럼 인용)이 실측으로 발생했던 경험(B단계에서 `SCHEMA_CITATION_FAIL` 버그를 실행 검증 중 발견) — 출력 형식 자체로 근거 제시를 강제해 코드가 검증 가능하게 만듦 |
| **Output Parsing** | 정규식 기반 마크다운 코드펜스 제거 후 `json.loads`(intent 분류) + sqlglot AST 파싱(SQL 블록의 안전성·스키마 인용 검증) | 게이트웨이가 JSON mode/함수 호출을 보장하지 않아, 정형 출력 규칙을 프롬프트로 강제하고 코드에서 관용적으로 파싱하는 방식을 택함 |
| **Monitoring** | 자체 구축 — app-db `token_usage`(호출 1건당 노드/모델/토큰, `tags`로 실험 그룹핑) + `run_metrics`(run 1회 요약: status/error_code/retries/latency) + `GET /runs/{id}/trace`(`get_state_history()` 기반 스텝 나열) | 외부 SaaS(LangSmith 등) 대신, "스키마 RAG 도입 전/후 토큰 -45%"류의 KPI 비교를 위한 맞춤 스키마가 필요했고 사내망 제약도 고려한 선택 |
