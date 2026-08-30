# D단계 구현 설계 — 난이도별 모델 라우팅 + 비용 대시보드

`data-access-copilot-plan.md` 6번 섹션 D그룹(8, 8b)의 상세 설계. B단계에서 이미 끝난 토큰 계측
인프라(`app/llm/base.py`의 `TokenCountingLLM`, `app/observability/cost_tracker.py`, `token_usage`
테이블) 위에 (1) 실제 라우팅 로직, (2) 그 결과를 읽는 API, (3) 화면을 얹는다.

## 1. `app/llm/router.py` (신규)

**문제**: `app/graph/nodes/intent.py`가 `GraphState.difficulty`(easy/medium/hard)를 이미 채우고
있지만, `app/graph/build.py`가 `AzureOpenAIChatClient()` 인스턴스 하나만 만들어 모든 노드가
공유한다 — difficulty 값이 어디서도 소비되지 않아 실제로는 항상 같은 모델(`LLM_CHAT_DEPLOYMENT`)
로만 호출된다.

**설계**:
- `.env` / `.env.example`에 배포 두 개로 분리
  - `LLM_CHAT_DEPLOYMENT_LOW` (기본값 `gpt-4.1-mini`, 기존 `LLM_CHAT_DEPLOYMENT`를 대체)
  - `LLM_CHAT_DEPLOYMENT_HIGH` (고성능 배포 — 게이트웨이에 실제 등록된 배포명 확인 필요, 미확정)
- `router.py`가 프로세스당 한 번씩 두 `TokenCountingLLM` 인스턴스(low/high)를 만들어 캐싱하고,
  `difficulty → client` 매핑을 제공:
  ```python
  def build_llm_router() -> dict[str, TokenCountingLLM]:
      low = TokenCountingLLM(AzureOpenAIChatClient(os.environ["LLM_CHAT_DEPLOYMENT_LOW"]))
      high = TokenCountingLLM(AzureOpenAIChatClient(os.environ["LLM_CHAT_DEPLOYMENT_HIGH"]))
      return {"easy": low, "medium": low, "hard": high}
  ```
  (medium을 low에 붙인 이유: 모델 티어는 2단계뿐이라 극단값만 고성능으로 승격 — 비용 절감이
  목적인 기능이므로 default는 저비용 쪽. 필요하면 나중에 medium만 별도 티어로 분리 가능.)
- `build_graph()`: `intent` 노드는 라우팅 이전 단계(아직 difficulty를 모름)라 지금처럼 고정
  저비용 클라이언트 사용. `sql_generation`/`execution` 노드 팩토리는 고정 `llm` 인자 대신
  `llm_router: dict[str, TokenCountingLLM]`를 받고, 노드 함수 내부에서
  `llm = llm_router[state.get("difficulty", "medium")]`로 매 호출 시점에 선택.
- `cost_tracker.record()` 호출 시 `tags`에 `difficulty`를 병합(`{**tags, "difficulty": state["difficulty"]}`)
  — `model` 컬럼만으로도 티어 구분은 되지만, 기존 `schema_rag_mode` 태그 비교 관례와 동일한
  방식으로 `tags->>'difficulty'` GROUP BY가 가능해짐.

## 2. 비용 조회 API — `app/api/cost_routes.py` (신규)

기존 `token_usage`/`run_metrics` 테이블과 `cost_tracker.get_run_usage()`는 있지만 이를 읽는
라우트가 없다. `domain_routes.py`와 같은 패턴으로 2개 엔드포인트 추가:

- `GET /runs/{run_id}/cost` — 해당 run의 노드별 호출 내역(`cost_tracker.get_run_usage`)과
  합계(총 input/output 토큰, 호출 수)를 반환. run 상세/드릴다운용.
- `GET /cost/summary?group_by={tags.schema_rag_mode|tags.difficulty|model}&domain=&since=` —
  `token_usage`를 지정된 축으로 `GROUP BY`해 그룹별 총 토큰/호출 수/run당 평균 토큰을 반환.
  스키마 RAG 전후 비교와 난이도별 분기 현황을 엔드포인트 하나로 커버(비교 축만 바꿔 호출).

`app/main.py`에 라우터 등록만 추가하면 됨 — 새 테이블/스키마 변경 없음(둘 다 B단계에서 이미
만든 `token_usage` 테이블만 읽음).

## 3. 프론트엔드 — `CostDashboard.tsx` (신규) + 네비게이션 연결

- `client/src/App.tsx`: `View` 타입에 `'cost'` 추가, `NAV_GROUPS`의 "비용 대시보드" 항목을
  `soon: true` → `view: 'cost'`로 전환(지금은 클릭 불가 플레이스홀더).
- `client/src/api/costClient.ts` (신규, `domainClient.ts` 패턴 그대로): 위 2개 엔드포인트 호출.
- `client/src/components/cost/CostDashboard.tsx` (신규): 화면 구성은 아래 디자이너 브리프의
  4존 레이아웃 참고. 기존 도메인 탐색기 화면과 동일하게 `styles/tokens.css` 토큰만 사용,
  신규 색상 추가 없음.

## 열린 결정 사항 (구현 착수 전 확인 필요)

1. `LLM_CHAT_DEPLOYMENT_HIGH`에 실제로 어떤 배포명을 쓸지 — 게이트웨이에 등록된 고성능 모델 확인 필요.
2. medium 난이도를 low/high 중 어디에 붙일지 — 위 설계는 low 기본, 필요시 조정.
3. `/cost/summary`의 `since` 기본 기간(예: 최근 7일) 및 `domain` 미지정 시 전체 도메인 합산 여부.

## 검증 방법 (계획 문서 7번 섹션 관례 준수)

- router 적용 후: `eval/token_cost_comparison.py`를 난이도 라우팅 on/off로 각각 돌려
  `token_usage.model` 컬럼에 두 배포명이 실제로 갈라지는지 확인(계획 문서 8~8b 검증 항목).
- API 추가 후: curl로 `/runs/{id}/cost`, `/cost/summary?group_by=tags.difficulty` 응답 확인.
- 프론트 완료 후: `docs/kpi-schema-rag-mode-ablation.md`의 실측 수치(rag 57,187 vs full_dump
  104,056 토큰)가 대시보드에 그대로 재현되는지 눈으로 대조.
