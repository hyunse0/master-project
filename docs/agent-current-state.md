# 에이전트 현재 구현 상태 정리

2026-08-30 기준, 코드베이스(`server/`, `client/`)를 직접 확인해 정리한 현황 문서. 원 설계는 [data-access-copilot-plan.md](./data-access-copilot-plan.md) 참고.

---

## 1. 에이전트 파이프라인 흐름

LangGraph 기반 단일 그래프(`server/app/graph/build.py`)가 도메인 하나에 바인딩되어 동작한다.

```
START → intent → schema_linking → schema_review → sql_generation
sql_generation --(VALUE_UNCONFIRMED, 재시도 남음)--> sql_generation
sql_generation --(SQL 확보)--> sql_review → validation
validation --(review_config.sql 켜짐, 실패)--> sql_review
validation --(review_config.sql 꺼짐, citation/anchor 실패, 재시도 남음)--> sql_generation
validation --(review_config.sql 꺼짐, SqlValidator 실패 또는 재시도 소진)--> END
validation --(전부 통과)--> execution
execution --(review_config.sql 켜짐, 실패)--> sql_review
execution --(review_config.sql 꺼짐, timeout/실행오류/zero-row, 재시도 남음)--> sql_generation
execution --(review_config.sql 꺼짐, 성공 또는 재시도 소진)--> END
```

### 노드별 역할

| 노드 | 파일 | 하는 일 |
|---|---|---|
| `intent` | `graph/nodes/intent.py` | 질문을 LLM으로 분류 — `task_type`/`metric`/`dimensions`/`time_range` + **난이도**(`easy`/`medium`/`hard`) + **질의유형**(`aggregate`/`list`/`cohort`) 태깅. 이 시점엔 difficulty를 모르므로 항상 저비용 모델 고정 |
| `schema_linking` | `graph/nodes/schema_linking.py` | Qdrant `schema_{domain}` 컬렉션에서 질문과 유사한 테이블 후보 검색 |
| `schema_review` | `graph/nodes/schema_review.py` | `review_config.schema`가 켜져 있으면 `interrupt()`로 정지(사람이 후보 테이블 체크박스 + 테이블별 컬럼 체크박스를 조정 — 핵심/PK-FK 컬럼은 항상 강제 포함, 관련/기타 컬럼만 상세 노출 여부 조정 가능), 꺼져 있으면 auto-pass |
| `sql_generation` | `graph/nodes/sql_generation/__init__.py` | few-shot 검색(`SqlRetriever`, 하이브리드 스코어) → 질의유형별 프롬프트 가이던스(`aggregate.py`/`list_type.py`/`cohort.py`의 `GUIDANCE` 상수) 주입 → 난이도별 모델(`llm/router.py`)로 SQL 생성. `VALUE_UNCONFIRMED` 감지 시 실제 DB에서 후보값을 조회해 재시도 피드백 생성 |
| `sql_review` | `graph/nodes/sql_review.py` | `review_config.sql`이 켜져 있으면 `interrupt()`로 정지(사람이 SQL 직접 수정 가능), 꺼져 있으면 auto-pass |
| `validation` | `graph/nodes/validation.py` | schema citation → value anchor → `SqlValidator`(SELECT-only 등) 3단계 게이트 |
| `execution` | `graph/nodes/execution.py` | 검증 통과 SQL 실행 + 결과 요약 생성 |

### 멀티 에이전트 / 라우팅 구현 상태
- **질의유형별 서브에이전트**: `intent` 노드가 분류한 `query_type`에 따라 `sql_generation` 내부에서 전용 프롬프트 가이던스(`aggregate.py`/`list_type.py`/`cohort.py`)를 주입. 노드 자체는 하나로 유지하고 가이던스만 분기하는 구조(계획 문서상 "그래프 골격 재사용" 방식 그대로 구현됨).
- **난이도별 모델 라우팅**: `llm/router.py`의 `select_llm()`이 `easy/medium→저비용, hard→고성능` 배포로 분기(`LLM_CHAT_DEPLOYMENT_LOW/HIGH`). 고성능 배포명이 아직 `.env`에 없으면 저비용으로 폴백.
- **재시도**: `review_config.sql`이 꺼져 있으면 `retry_count` 기반 자동 재생성(최대 2회, `tags.max_retries`로 조정 가능). 켜져 있으면 실패 시 무조건 `sql_review`로 되돌아가 사람이 고치거나 재승인할 때까지 반복(자동 재생성이 사람 입력을 덮지 않도록).

### Human-in-the-loop / 실행 API
- `POST /runs`, `POST /runs/{id}/resume` — 동기 호출, `graph.invoke()`가 다음 interrupt 또는 그래프 종료까지 블로킹. `review_config`가 둘 다 꺼져 있으면 한 번의 호출로 끝까지 실행.
- `GET /runs/{id}` — LangGraph 체크포인트를 다시 읽지 않고 `run_manager`가 캐싱한 마지막 응답을 반환.
- `GET /runs` — 실행 히스토리 목록/필터/검색.
- `GET /runs/{id}/trace` — `graph.get_state_history()`로 노드별 재시도 횟수/다음 노드 노출.
- 체크포인터는 `PostgresSaver`(app-db), `run_id`가 `thread_id`로 그대로 쓰인다.

### MCP 노출 (완료)
`app/api/mcp.py` — 기존 FastAPI 프로세스에 `/mcp`로 서브마운트. 6개 tool 전부 읽기이거나 검증 게이트를 통과해야만 실행되는 경로:
`get_domain_status`, `list_tables`, `get_table_detail`, `search_schema`, `search_few_shot_examples`, `run_nl2sql_query`(자동 모드 고정 — interrupt/resume 미지원).

---

## 2. 에이전트 관리 메뉴 — 세팅 user journey

사이드바 "에이전트 관리" 그룹 하위 화면들. **도메인 등록 자체는 화면이 아니라 CLI 스크립트**로 이뤄지고, 그 외 항목들은 화면에서 조회·관리한다.

### 2.1 도메인 등록 (화면 없음, 스크립트)
```bash
python scripts/register_domain.py --name <domain> --host ... --dbname ... --schemas ... --activate
```
`domain_connections` 테이블에 접속정보를 암호화(Fernet) 저장하고 `--activate`로 활성 도메인을 전환(도메인은 항상 최대 1개, DB 유니크 제약으로 강제). 도메인 팩 폴더(`server/domains/<name>/`)도 이때 자동 생성.

### 2.2 [화면] 도메인 관리
연결된 DB의 상태/테이블/컬럼을 조회하는 화면(읽기 전용, 등록/전환 기능 없음).
- 상단 상태 바: `GET /domain/status` — 연결 여부, host/port/dbname, 허용 스키마
- 테이블 목록: `GET /domain/tables` — 테이블명/코멘트/컬럼 수
- 테이블 상세: `GET /domain/tables/{table}` — 컬럼(타입/코멘트/PK)/FK 클릭 시 조회
- (API만 존재, 화면 미연동) `GET /domain/schema-search?q=` — Qdrant 시맨틱 검색

### 2.3 [화면] Few-shot 예제 관리
사람이 승인 과정에서 SQL을 직접 고친 run을 few-shot 예제로 채택하는 3단계 파이프라인:
1. **후보** — 실행 히스토리 중 "사람이 SQL을 수정해 승인한 run"(`sql_edited=true`)이 자동으로 후보 목록에 뜸(`GET /fewshot/candidates`). 사이드바에 후보 건수 배지 표시.
2. **저장됨** — 후보를 채택하면 `POST /fewshot/entries`로 도메인 팩의 `few_shot.json`에 기록(Qdrant엔 아직 미반영).
3. **반영됨** — `POST /fewshot/seed`로 Qdrant `sql_knowledge_{domain}` 컬렉션에 실제 색인, 이후 `sql_generation`이 검색해 사용. 반영 여부는 저장하지 않고 매 조회 시 Qdrant에 직접 있는지 확인해 판정.
- 질문 텍스트 검색, 항목 삭제(`DELETE /fewshot/entries/{id}`) 지원.

### 2.4 [화면] Golden Set 평가
`eval/*.py` 스크립트가 남긴 지표를 조회만 하는 대시보드(재실행은 CLI로만 가능):
- 난이도별 정답률(`execution_accuracy.py`)
- 스키마 매핑 정확도 — precision/recall/f1(`schema_mapping_accuracy.py`)
- 요약 충실도 + 실패 사례 목록(`condition_summary_faithfulness.py`)
- Self-correction 귀인 — 재시도 결과 3분류 + 실패유형별 교정 건수(`self_correction_ablation.py`)
- 토큰/비용 비교 — 태그값별(`schema_rag_mode`, `routing_mode` 등) 비교(`token_cost_comparison.py`)

### 2.5 [화면] 비용 대시보드
- run별 토큰 사용량 상세(`GET /runs/{id}/cost`) — 노드별/모델별 집계
- 최근 실행 목록 + 토큰 합계(`GET /cost/recent-runs`)
- 전체 요약 + `schema_rag_mode`/`difficulty`/`model` 축별 그룹핑(`GET /cost/summary`)

### 2.6 [화면] MCP 연동
연결 정보, 연결 방법 안내, 노출된 tool 목록, 안전장치(raw SQL 실행 tool을 의도적으로 뺀 이유 등)를 보여주는 안내/레퍼런스 화면.

### 2.7 검토 정책 — 미구현 (SOON)
사이드바에 항목은 있으나 `soon: true`로 비활성화. `review_config.{schema,sql}`은 현재 "질의 실행" 화면에서 실행 시점에 토글하는 방식으로만 존재하고, 별도 정책 관리 화면은 없음.

---

## 3. 에이전트 메뉴 — 사용 user journey

사이드바 "에이전트" 그룹 하위 화면들.

### 3.1 [화면] 질의 실행 (`QueryRunTab`)
1. 자연어 질문 입력 + `review_config`(스키마 검토/SQL 검토 on-off) 설정 후 실행
2. **진행 상태 레일**(`StageRail`) — 의도 분류 → 스키마 탐색 → SQL 생성 → 검증 → 실행, 5단계를 스테이지 박스로 표시. 동기 API 특성상 "지금 어느 요청이 떠 있는가" 기준으로 진행 상태를 앵커링(실시간 스트리밍은 아님)
3. 1단계 결과(난이도/task_type)는 즉시 요약 배너로 표시
4. **스키마 검토 게이트 켜짐** → `SchemaReviewCard`에서 후보 테이블 체크박스로 확정, 체크된 테이블마다 컬럼 패널이 펼쳐져 핵심(PK/FK, 잠금)·관련(기본 체크)·기타(펼쳐야 보이는 이름만 목록, 기본 미체크) 컬럼을 조정 가능 → 승인(`resume`)
5. **SQL 검토 게이트 켜짐** → `SqlReviewCard`에서 SQL 직접 수정 가능, 수정 시 사유(`correction_reason`) 입력 → 승인(`resume`). 수정된 SQL은 재생성 없이 곧바로 검증으로 흘러감(검증 우회 불가)
6. 검증 실패 시 스테이지별 체크리스트(스키마 인용/값 존재/안전성/실행)로 실패 지점 표시, 재시도 횟수 배지
7. 완료 시 `ResultCard` — SQL, 결과 표, 요약 문장 렌더링. 실패 시 `FailedCard`로 재시작 유도
8. 각 스테이지 클릭 시 해당 시점 스냅샷(`StageSnapshotCard`) 조회 가능

### 3.2 [화면] 실행 히스토리 (`HistoryTab`)
과거 run 목록(`GET /runs`, 도메인/상태/질문 검색 필터) + 클릭 시 상세 패널(`RunDetailPanel`)에서 SQL/결과/재시도 이력 확인. Few-shot 관리/비용 대시보드에서 특정 run으로 딥링크 가능.

---

## 4. 계획 문서 대비 미구현 항목

`data-access-copilot-plan.md` 기준으로 아직 구현되지 않았거나 계획과 다르게 축소된 부분.

| 항목 | 계획 문서 근거 | 현재 상태 |
|---|---|---|
| **검토 정책 화면** | 화면 지도(`screen-spec.html`)에 명시된 화면 | 사이드바에 SOON 뱃지만 있고 미구현. `review_config`는 질의 실행 화면에서 매 실행마다 토글하는 방식뿐 |
| **결과 시각화 고도화(Tier2.5)** | `ResultChart.tsx` — 집계/단건/시계열에 따라 차트 자동 선택 | 미구현. 현재 `ResultCard`는 표 형태로만 렌더링, 차트 컴포넌트 없음 |
| **RBAC 목업(Tier3)** | 역할 선택 시 조회 가능 도메인이 달라지는 목업 토글, 또는 "Out of Scope" 명시 | 코드/화면 어디에도 역할 선택 UI 없음. 명시적 Out-of-Scope 문구도 화면에 없음 |
| **교정 사례 학습 루프 자동화(Stretch, I그룹)** | 사용자가 승인/수정한 SQL을 few-shot에 "자동으로" 재투입하는 RAG 축적 루프 | **부분 구현**: 후보 추출→저장→Qdrant 반영 3단계는 있으나, 전부 사람이 화면에서 수동으로 채택/반영 버튼을 눌러야 함. "자동 재투입"은 아님 |
| **실시간 스트리밍(SSE)** | section 5.7 — 필요해지면 별도 작업으로 분리 예정이라 명시 | 계획대로 미구현·보류 상태 유지. `POST /runs` 동기 방식 그대로 |
| **골든셋/few-shot 데이터 자산** | `domains/<domain>/golden_set.json`, `few_shot.json`은 "사람이 채워야 함"으로 명시 | 채우는 화면(Few-shot 관리)은 완성됐지만, golden_set은 조회 화면만 있고 작성/편집 화면은 없음(여전히 파일을 직접 작성해야 함) |
| **난이도별 모델 실배포 분기** | `LLM_CHAT_DEPLOYMENT_HIGH` 설정 시 실제 고성능 모델로 분기 | 라우팅 로직 자체는 완성됐으나, 고성능 배포명이 `.env`에 없으면 저비용으로 폴백 — 실제 두 모델 간 분기 효과는 배포 환경에 따라 달라짐 |
| **`schema-search` 화면 연동** | 도메인 탐색기 4존 레이아웃(상태/목록/검색/상세) | `GET /domain/schema-search`는 API로 존재하지만 "도메인 관리" 화면에는 아직 연동되지 않음(상태/목록/상세 3존만 연동됨) |

### 계획과 다르게 구현된 부분 (참고)
- MCP 클라이언트 라이브러리가 `FastMCP`→`MCPServer`, `streamablehttp_client`→`streamable_http_client`로 개명(설치된 `mcp==2.1.1` 기준 반영) — 계획 문서의 옛 API명과 다름.
- 노출 tool이 계획된 5개가 아니라 6개(`search_few_shot_examples` 포함) — 계획 문서 자체가 10번 항목에서 6개로 갱신되어 있음.

---

## 5. 단계별 검증 체크리스트

`data-access-copilot-plan.md` 7번 섹션("검증 방법")을 기준으로, 지금 로컬 환경에서 직접 눌러보고 확인할 수 있는 체크리스트로 옮긴 것. 코드는 존재가 확인됐지만 **실제 동작을 눈으로 확인하는 것은 별개**이므로 전부 미체크 상태로 둔다 — 계획 문서가 "완료"로 표시한 항목도 직접 재현해보는 걸 권장(괄호에 참고용으로 표시).

### 0. 프레임워크 기본 세팅
- [ ] `cd server && uvicorn app.main:app --reload --port 8000` 기동 후 `curl http://localhost:8000/health` 정상 응답
- [ ] `cd client && npm run dev` 기동 후 `http://localhost:5173` 기본 페이지 로딩

### A. 데이터 계층 (계획 문서상 완료 표시)
- [ ] `scripts/test_connection.py --domain <활성도메인>` 실행 → 연결 성공, 테이블 목록·코멘트·PK·FK 텍스트로 정확히 출력
- [ ] `python app/knowledge/schema_indexer.py --domain <활성도메인>` 실행 → `schema_<domain>` Qdrant 컬렉션에 테이블 수만큼 색인됐는지 확인
- [ ] 실제 자연어 질의로 스키마 시맨틱 검색(`GET /domain/schema-search?q=...` 또는 MCP `search_schema`) 호출 → 관련 테이블이 상위로 검색되는지 확인
- [ ] `scripts/seed_few_shot.py --domain <활성도메인>` 실행 후 `sql_knowledge_<domain>` 컬렉션에 few-shot 예제 수 확인

### B. 코어 파이프라인 (자동 모드)
- [ ] `scripts/run_graph_cli.py --domain <활성도메인> --question "..."` 로 자동 모드 전체 파이프라인이 SQL 실행까지 끝까지 도는지 확인
- [ ] 위 실행 결과에 `difficulty`/`query_type`이 정상적으로 채워지는지 확인 (state·로그 기준)
- [ ] "질의 실행" 화면에서 `review_config`를 둘 다 끄고 실행 → SQL/결과 표가 정상 렌더링되는지 확인
- [ ] `eval/execution_accuracy.py` 실행해 baseline Execution Accuracy 수치 확보 (golden_set.json이 도메인에 없으면 스킵됨 — 있는지 먼저 확인)
- [ ] 의도적으로 실패하는 질문(예: 존재하지 않는 값)으로 `retry_count` 기반 자동 재시도가 실제로 도는지, 재시도 횟수가 응답에 반영되는지 확인

### C. Human-in-the-loop (핵심 슬라이스)
- [ ] "질의 실행" 화면에서 스키마 검토 게이트를 켜고 질의 실행 → 후보 테이블 체크박스 조정 → 승인(resume) → 다음 단계로 정상 진행
- [ ] 같은 화면에서 컬럼이 많은 테이블을 체크 → 컬럼 패널이 펼쳐지고 핵심/관련/기타 티어가 구분돼 보이는지, "기타 컬럼 N개 보기"를 펼쳐 컬럼을 추가로 체크했을 때 승인 후 실제 SQL 생성 프롬프트(`schema_text`)에 반영되는지 확인
- [ ] SQL 검토 게이트를 켜고 질의 실행 → SQL 직접 수정 → 수정 사유 입력 → 승인(resume) → 수정한 SQL 그대로 검증·실행되는지 확인(자동 재생성으로 덮이지 않는지)
- [ ] 검증 실패를 의도적으로 유발한 뒤(SQL 검토 켠 상태) `sql_review`로 되돌아가는지, `retry_count`와 무관하게 반복되는지 확인
- [ ] 앱을 재시작한 뒤 검토 대기 중이던 run이 `GET /runs/{id}`로 여전히 조회되는지 확인(PostgresSaver 영속성)
- [ ] `GET /runs/{id}/trace`로 노드별 재시도 횟수·다음 노드가 시간순으로 정확히 나오는지 확인
- [ ] 프로토타입 HTML(`data-access-copilot-prototype.html`)과 나란히 놓고 동일 시나리오로 시각적/기능적 비교

### D. 비용/관측성
- [ ] 동일 질문을 `schema_rag_mode=rag` / `full_dump`로 각각 실행(또는 `eval/token_cost_comparison.py`)해 토큰 수 차이 확보
- [ ] "비용 대시보드" 화면에서 run별 토큰 사용량, `schema_rag_mode`/`difficulty`/`model` 그룹별 집계가 실제 데이터와 일치하는지 확인
- [ ] `.env`에 `LLM_CHAT_DEPLOYMENT_HIGH`를 설정한 뒤 `hard` 난이도 질문이 실제로 다른 모델로 라우팅되는지 로그로 확인(현재는 폴백 상태라 분기 효과가 없을 수 있음)

### E. 멀티에이전트 확장
- [ ] 집계형/리스트형/코호트형 질문을 각각 던져 `query_type`이 의도한 대로 분류되는지, `sql_generation`이 서로 다른 가이던스(GUIDANCE)로 생성하는지 확인
- [ ] "질의 실행" 화면의 1단계 요약 배너/스테이지 메타에 질의유형이 표시되는지 확인

### F. MCP 노출 (계획 문서상 완료 표시)
- [ ] `uvicorn app.main:app` 기동 후 mcp 클라이언트(`streamable_http_client`+`ClientSession`)로 `http://localhost:8000/mcp` 접속 → `list_tools()`로 6개 tool 노출 확인
- [ ] 6개 tool 각각 개별 호출해 REST 대응 엔드포인트와 같은 필드 구조로 응답하는지 확인
- [ ] `run_nl2sql_query`로 실제 자연어 질문 실행 → SQL 생성부터 결과 반환까지 end-to-end 확인
- [ ] `POST /runs`(REST)가 `execute_run` 추출 이후에도 기존과 동일하게 동작하는지 회귀 확인

### H. 평가
- [ ] `eval/schema_mapping_accuracy.py`, `eval/condition_summary_faithfulness.py`, `eval/self_correction_ablation.py` 각각 실행해 "Golden Set 평가" 화면의 해당 패널에 결과가 반영되는지 확인
- [ ] "Golden Set 평가" 화면에서 golden_set.json이 없는 도메인일 때 "골든셋 없음" 상태가 올바르게 표시되는지 확인
- [ ] 토큰 비교/비용-정확도 실험 결과가 발표 자료로 쓸 수 있을 만큼 표/그래프로 정리되는지 확인

### 아직 화면/기능이 없어 체크리스트 자체가 성립하지 않는 항목
아래는 4번 섹션에서 "미구현"으로 분류된 항목이라 지금 시점엔 검증할 대상이 없다 — 구현 후 별도 체크리스트 추가 필요:
- [ ] 검토 정책 관리 화면
- [ ] 결과 시각화(차트) 자동 선택
- [ ] RBAC 목업 토글
- [ ] 교정 사례 학습 루프의 "자동" few-shot 재투입
- [ ] golden_set.json 작성/편집 화면
