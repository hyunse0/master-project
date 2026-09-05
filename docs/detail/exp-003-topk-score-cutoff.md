# EXP-003 고정 Top-5 → Top-10 풀 + 상대 스코어 컷오프로 후보 테이블 수 동적 조정

- **날짜**: 2026-08-31
- **상태**: ❌ 폐기

## 배경 / 가설

EXP-001 baseline에서 스키마 매핑 recall은 90.4%로 이미 천장에 가까운 반면 precision은 28.4%로 낮았다. `poc_prostate` 도메인의 전체 테이블 수는 16개뿐이고, golden_set 대부분의 질문은 1~2개 테이블만 있으면 풀리는 단순 질의다. 이 상태에서 `_TOP_N_TABLES=5`로 고정해두면, 리트리버가 정답 테이블을 잘 찾아내도(recall은 이미 90%) 후보에 항상 5개를 채워 넣는 구조상 precision이 기계적으로 낮게 눌린다는 가설을 세웠다. EXP-002의 "새롭게 배운 것"에서도 같은 방향(후보 축소)이 다음 시도로 제안된 바 있다. 고정 K 대신 "최고점수 대비 상대적으로 점수가 낮은 후보는 자른다"는 동적 컷오프로 바꾸면 불필요한 후보가 줄어 precision(및 F1)이 개선될 것으로 예상했다.

## 변경 내용

- `server/app/graph/nodes/schema_linking.py`: `_TOP_N_TABLES = 5`(고정 limit)를 `_MAX_TABLES = 10`(Qdrant 조회 풀 크기) + `_SCORE_RATIO = 0.75`(1위 후보 점수 대비 이 비율 미만인 후보 제외)로 교체. Qdrant에서 최대 10개를 가져온 뒤, 1위 점수 × 0.75 미만인 포인트를 필터링해서 `candidates`/`candidate_details`를 구성하도록 변경(항상 1위 후보는 남으므로 빈 결과가 되는 경우는 없음).
- 다른 파일은 건드리지 않음 — 단일 변인 통제.

## 측정 방법

- 비교축(A/B): 고정 Top-5(EXP-001 baseline) vs Top-10 풀 + 상대 스코어 컷오프(0.75)
- 사용한 도구: `eval/execution_accuracy.py` (스키마 매핑 precision/recall/F1을 execution accuracy와 동시 산출)
- 데이터셋: `domains/poc_prostate/golden_set.json` 19문항 — `schema_linking.py`/`embedder.py`/golden_set이 EXP-001 이후 변경되지 않았음을 git log로 확인한 뒤 baseline 수치를 "변경 전"으로 재사용(EXP-002와 동일한 방식)
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  ```

## 결과

| 지표 | 변경 전 (EXP-001) | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (19문항) | 9/19 (47.4%) | 9/19 (47.4%) | 없음 |
| Schema Mapping Precision | 28.4% | 30.9% | +2.5pp |
| Schema Mapping Recall | 90.4% | 92.1% | +1.7pp |
| Schema Mapping F1 | 41.3% | 39.7% | -1.6pp |

## 분석 및 결정

가설대로 precision과 recall은 둘 다 소폭 올랐지만, 정작 headline 지표인 F1은 오히려 떨어졌다. 원인은 이 스크립트의 precision/recall/F1이 전부 "질문별로 P·R·F1을 구한 뒤 평균"하는 macro-average 방식(`eval/execution_accuracy.py`의 `_prf1`)이라는 점에 있다 — macro-평균 P·R이 개선돼도 macro-평균 F1이 함께 개선된다는 보장이 없다(F1은 질문별로 먼저 계산된 뒤 평균되므로, 컷오프로 후보 수가 줄어든 질문들의 분포가 달라지면서 역전될 수 있다). Execution Accuracy는 완전히 동일해 실제 SQL 생성 결과에는 영향이 없었다. 개선이라 부를 근거가 F1 기준으로는 없고, EXP-002(-1.3pp)와 비슷한 크기의 변동이라 노이즈 범위일 가능성도 높다 — 최소한 "뚜렷한 개선"이라는 가설은 이번에도 기각. `schema_linking.py`를 `_TOP_N_TABLES=5` 고정 방식으로 되돌렸다.

## 새롭게 배운 것

- Recall 90%·precision 28%라는 baseline 숫자만 보고 "후보를 줄이면 precision과 F1이 같이 오를 것"이라 예상했는데, macro-average F1은 그렇게 단순하게 따라오지 않았다 — precision·recall이 개별적으로 개선돼도 F1(질문별 계산 후 평균)은 반대로 움직일 수 있다는 걸 숫자로 확인했다. 이후 스키마 매핑 개선 실험은 precision/recall뿐 아니라 F1도 반드시 같이 보고해야 한다.
- 16개 테이블짜리 작은 도메인에서는 Top-K를 5→10 풀로만 넓혀도(컷오프로 걸러내더라도) 눈에 띄는 개선이 안 나온다 — 이 도메인 규모에서는 단순 리트리버 파라미터 튜닝의 여지가 생각보다 작을 수 있다. 다음 시도라면 (a) `_SCORE_RATIO` 값 자체를 여러 값으로 스윕해보거나, (b) EXP-002가 제안했던 "힌트를 후보 재정렬/필터링에 쓰는" 방향, 혹은 (c) 리트리버 파라미터가 아니라 schema_review 단계에 실제 LLM 기반 재순위화를 넣는(현재는 review_config.schema가 꺼져있으면 순수 human-interrupt passthrough라 아무 필터링도 없음) 더 큰 구조 변경 쪽이 유망해 보인다.

## 한계

- 골든셋 19문항, 단일 실행(반복 없음) — 통계적 유의성 없음.
- "변경 전" 수치는 이번 실행이 아니라 EXP-001 baseline을 재사용한 것 — 그 사이 LLM 응답 자체의 변동성(비결정적 생성)까지는 통제하지 못했다.
- `_SCORE_RATIO=0.75`, `_MAX_TABLES=10` 두 파라미터를 한 번에 고정해 시도한 것이라, 이 조합이 최적이 아닐 가능성이 있다 — 파라미터 스윕은 하지 않았다.
