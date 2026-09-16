# EXP-019 스키마 검색에 Qdrant dense+sparse(BM25) 하이브리드 도입

- **날짜**: 2026-09-15
- **상태**: ✅ 채택

## 배경 / 가설

dense 임베딩(`text-embedding-3-small`)은 `exam_cd`, `ADT001` 같은 컬럼명·코드값처럼 의미 정보가 희박한 식별자를 질문이 그대로 언급해도 잘 못 찾아낼 수 있다는 우려가 있었다(EXP-017/018에서 "SQL 생성이 코드값을 모른다"는 병목을 domain_notes로 우회한 바 있음 — 그 우회 이전 단계인 schema_linking 검색 자체의 한계). Qdrant는 dense+sparse(BM25) 하이브리드 검색을 네이티브로 지원한다(`SparseVectorParams(modifier=Modifier.IDF)` + `Prefetch`/`FusionQuery`). schema_linking의 테이블 검색에 sparse 축을 추가하면 정확 토큰 매칭이 dense의 약점을 보완해 스키마 후보 recall이 개선되고, 그 하류인 Execution Accuracy도 개선될 것으로 예상했다.

## 변경 내용

- `app/embedding/sparse_embedder.py`(신규): fastembed `Qdrant/bm25` 래퍼 — 색인용 `embed_documents()`(문서 가중치 포함), 질의용 `embed_query()`(순수 용어빈도, IDF는 Qdrant가 컬렉션 통계로 서버사이드 계산)
- `app/knowledge/schema_indexer.py`: `schema_{domain}` 컬렉션을 unnamed 단일 dense 벡터 → named `dense`(1536차원) + sparse `bm25`(`Modifier.IDF`) 하이브리드 컬렉션으로 재구성, 색인 시 두 벡터 모두 계산해 업서트
- `app/graph/nodes/schema_linking.py`: 단일 `query_points(query=embedding)` → `Prefetch`(dense 20개 + sparse 20개) + `FusionQuery(fusion=Fusion.RRF)`로 교체
- `app/graph/build.py`: `SparseEmbedder` 인스턴스화해 `schema_linking` 노드에 주입
- `app/api/domain_routes.py`(`GET /domain/schema-search`), `app/api/mcp.py`(`search_schema` tool): 같은 컬렉션을 쓰는 다른 두 진입점도 동일하게 하이브리드로 전환 — 안 바꾸면 named vector로 바뀐 컬렉션에 unnamed 쿼리를 던져서 깨지는 지점
- `requirements.txt`: `fastembed==0.8.0` 추가

## 측정 방법

- 비교축(A/B): 같은 하이브리드 컬렉션(dense+sparse 둘 다 이미 색인됨)에 대해 `schema_linking`의 쿼리 전략만 dense-only ↔ dense+sparse RRF fusion으로 전환 — 컬렉션 재색인 없이 쿼리 로직만 바꿔서 통제 변인을 검색 전략 하나로 좁혔다.
- 사용한 도구: `eval/execution_accuracy.py`
- 데이터셋: `domains/poc_prostate/golden_set.json` — 23대화 38턴(턴1 33건/턴2 4건/턴3 1건)
- 재현 명령어:
  ```bash
  # 컬렉션은 이미 하이브리드로 색인된 상태 (python app/knowledge/schema_indexer.py --domain poc_prostate)
  # before: schema_linking.py의 쿼리를 dense-only(query=embedding, using="dense")로 임시 되돌린 뒤
  python eval/execution_accuracy.py --domain poc_prostate
  # after: RRF fusion 쿼리로 원복한 뒤
  python eval/execution_accuracy.py --domain poc_prostate
  ```

## 결과

| 지표 | before (dense-only) | after (dense+sparse RRF) | 변화 |
|---|---|---|---|
| Execution Accuracy | 17/38 (44.7%) | 24/38 (63.2%) | **+18.5pp** |
| 턴1 | 16/33 (48.5%) | 20/33 (60.6%) | +12.1pp |
| 턴2 | 1/4 (25.0%) | 3/4 (75.0%) | +50.0pp |
| 턴3 | 0/1 (0.0%) | 1/1 (100.0%) | 표본 1건 |
| Schema Mapping precision | 78.9% | 78.3% | -0.6pp |
| Schema Mapping recall | 92.1% | 98.2% | +6.1pp |
| Schema Mapping F1 | 81.6% | 84.7% | +3.1pp |
| Condition Summary Faithfulness | 31/34 (91.2%) | 30/37 (81.1%) | 분모 변화(아래 분석 참고), 채택 판단에는 미반영 |

## 분석

- Execution Accuracy가 대리지표보다 훨씬 크게 개선(+18.5pp) — [1.5절 채택 판단 원칙](../kpi-experiment-log.md#15-채택-판단-원칙--대리지표proxy-metric-단독-개선은-채택-근거가-아니다)이 요구하는 "진짜 지표 개선"을 충족한다.
- Schema Mapping recall이 92.1%→98.2%로 거의 포화(38턴 중 recall 미스가 사실상 1건 수준)에 도달 — "sparse가 dense가 놓치던 정확 식별자 매칭을 보완한다"는 가설과 방향이 일치한다.
- precision은 사실상 그대로(78.9%→78.3%, 오차 범위) — recall 개선이 "후보를 마구잡이로 더 넣어서" 생긴 부작용이 아니라는 근거.
- Faithfulness 판정 건수가 34건→37건으로 늘어난 건 실행까지 도달한 턴 자체가 늘었기 때문(SQL이 안 나오거나 실행이 실패하면 애초에 요약 판정 대상에서 빠짐) — 분모가 다른 지표라 91.2%→81.1%를 액면 그대로 "충실도가 나빠졌다"로 읽으면 안 된다.

## 한계

- 이 변경엔 `schema_rag_mode`처럼 `tags`로 온/오프하는 런타임 토글이 없어서, before 측정은 코드를 일시적으로 되돌려 재실행하는 방식으로 쟀다 — `token_cost_comparison.py --compare`처럼 한 번에 비교표가 나오는 방식이 아니다. 이 축을 계속 실험할 계획이면 `tags`에 `schema_search_mode`(dense/hybrid) 같은 토글을 추가해두는 게 다음에 편하다.
- 골든셋 38건은 여전히 작은 표본 — EXP-016에서 관찰된 것처럼 코드 변경 없이도 재실행 시 몇 건 단위 노이즈가 있을 수 있다. 다만 이번 +7건(17→24) 차이는 그 노이즈 폭보다 크고, Schema Mapping recall 개선과 방향이 일치해 우연으로 보기는 어렵다.
- `fastembed` 신규 의존성 추가(`onnxruntime` 등 약 30MB+) — 이 프로젝트가 지금까지 유지해온 "가벼운 의존성"(numpy조차 안 씀) 기조와는 트레이드오프.
- `Qdrant/bm25` 모델의 토크나이저/불용어 리소스는 최초 실행 시 HuggingFace Hub에서 내려받아 로컬에 캐시한다 — 배포 환경에서 HF Hub 접근이 막혀 있으면 사전 캐시가 필요하다.

## 새롭게 배운 것

dense 임베딩 단독으로도 골든셋 대부분 문항을 어느 정도는 처리했지만(before도 44.7%), 코드값·컬럼명이 섞인 질문에서 조용히 recall을 깎아먹고 있었다는 게 이번에 수치로 확인됐다. Qdrant의 named vector + sparse + RRF fusion은 기존 dense 파이프라인 코드를 거의 그대로 두고 "쿼리 전략만" 바꿔 끼울 수 있어서, 컬렉션 스키마 자체를 바꿔야 하는 변경치고는 침습성이 낮았다.
