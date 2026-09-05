# EXP-002 intent의 미사용 `table_hints`를 `schema_linking` 검색 쿼리에 연결

- **날짜**: 2026-08-31
- **상태**: ❌ 폐기

## 배경 / 가설

코드 리뷰 중 `intent_node`가 `table_hints`(질문에 언급된 테이블/도메인 표현)를 뽑아내지만 `schema_linking_node`를 포함해 어디서도 실제로 읽지 않는다는 걸 확인했다 — LLM 토큰만 쓰고 버려지는 죽은 필드였다. 이 값을 `schema_linking`의 임베딩 검색 쿼리에 섞어 넣으면(현재도 `intent` 요약 문자열을 쿼리에 추가하는 것과 같은 패턴) 스키마 매핑 정확도(EXP-001 baseline: precision 28.4% / recall 90.4% / F1 41.3%)가 개선될 것이라는 가설을 세웠다.

## 변경 내용

- `server/app/graph/nodes/intent.py`: 출력 필드명을 `table_hints` → `schema_hints`로 개명(실제 DB 테이블명이 아니어도 됨을 프롬프트에 명시)
- `server/app/graph/nodes/schema_linking.py`: 임베딩용 `query_text`에 `관련 키워드: {schema_hints}` 줄을 추가로 붙임
- `server/app/graph/state.py`: `table_hints` → `schema_hints` 필드명 변경
- 같은 세션에서 `intent_status`/`intent_error`(LLM 실패 관측성) 필드 추가와 difficulty 판정 기준 프롬프트 명시도 같이 반영됐다 — 이 둘은 스키마 매핑 정확도에 영향을 줄 메커니즘이 없어(관측성 필드는 순수 추가, difficulty 문구는 라우팅에만 영향 — 현재 `LLM_CHAT_DEPLOYMENT_HIGH` 미설정으로 라우팅 자체가 실질 효과 없음) 통제 변인 오염은 없다고 판단했다.

## 측정 방법

- 비교축(A/B): `schema_hints`를 검색 쿼리에 연결하기 전(EXP-001 baseline, 같은 코드베이스·같은 golden_set) vs 연결한 후
- 사용한 도구: `eval/execution_accuracy.py` (스키마 매핑 precision/recall/F1을 execution accuracy와 동시 산출)
- 데이터셋: `domains/poc_prostate/golden_set.json` 19문항 — EXP-001과 동일 파일(그 사이 `schema_linking.py`/`retriever.py`/`embedder.py`/golden_set 어느 것도 변경되지 않았음을 git log로 확인 후 baseline 수치를 그대로 재사용)
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  ```

## 결과

| 지표 | 변경 전 (EXP-001) | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (19문항) | 9/19 (47.4%) | 9/19 (47.4%) | 없음 |
| Schema Mapping Precision | 28.4% | 27.4% | -1.0pp |
| Schema Mapping Recall | 90.4% | 88.6% | -1.8pp |
| Schema Mapping F1 | 41.3% | 40.0% | -1.3pp |

## 분석 및 결정

precision·recall이 둘 다 소폭 하락했고 개선은 전혀 관측되지 않았다. 19문항 단발 실행(비결정적 LLM 호출, 반복 측정 없음)이라 -1~2pp 차이는 노이즈 범위일 가능성이 높지만, 최소한 "뚜렷한 개선"이라는 가설은 기각됐다. `schema_linking.py`의 쿼리 텍스트 연결을 되돌리고, 다시 죽은 필드로 남기지 않기 위해 `intent_node`의 `schema_hints` 출력 자체를 프롬프트에서 제거했다(불필요한 LLM 출력 토큰 절감 겸).

## 새롭게 배운 것

- intent가 뽑아낸 "질문에 언급된 테이블/도메인 표현"은 실제 스키마 검색 품질에 그대로 도움이 되지 않았다 — 단순히 검색 쿼리 텍스트에 키워드를 추가하는 방식으로는 개선되지 않는다는 뜻이지, 도메인 힌트 자체가 무의미하다는 뜻은 아니다. 재시도한다면 (a) 임베딩 텍스트에 섞는 대신 후보 재정렬/필터링에 쓰거나, (b) EXP-001에서 이미 확인된 "recall 90%·precision 28%" 문제(불필요하게 많은 테이블을 후보로 끌고 옴)에 맞춰 힌트를 후보 축소용으로 쓰는 방향이 더 맞을 수 있다.
- "일단 넣어보면 나아지겠지"라는 직관이 실측에서 빗나간 사례 — intent 단계 출력을 늘리는 게 항상 다운스트림에 도움이 되는 게 아니라는 걸 숫자로 확인했다.

## 한계

- 골든셋 19문항, 단일 실행(반복 없음) — 통계적 유의성 없음. -1~2pp 차이가 실제 효과인지 LLM 응답 변동성인지 이 실험만으로는 구분 불가.
- 같은 실행에 `intent_status`/`intent_error`·difficulty 문구 변경이 같이 들어가 있어 엄밀한 단일 변인 통제는 아니었다(다만 위에서 설명한 이유로 이 둘이 스키마 매핑 지표에 영향을 줄 메커니즘은 없다고 판단).
