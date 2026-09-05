# EXP-005 schema_review에 LLM 기반 closed-set 재선정 추가 + schema_text 재구성

- **날짜**: 2026-08-31
- **상태**: ❌ 폐기

## 배경 / 가설

EXP-003·EXP-004는 둘 다 `schema_linking`의 벡터 검색/재정렬 파라미터만 건드렸는데, 설계 도중 `confirmed_schema`(schema_review의 산출물)가 실제로는 few-shot 예제 검색(`table_hints`)에만 쓰이고, SQL 생성 프롬프트의 `[스키마]` 섹션(`schema_text`)은 `schema_linking`이 만든 값을 그대로 쓴다는 걸 발견했다(`sql_generation/__init__.py:58`가 `state.get("schema_text")`를 직접 사용, `confirmed_schema`는 참조 안 함) — 사람이 직접 검토해서 테이블을 추려도 SQL 생성 LLM이 보는 스키마 설명엔 반영 안 되는, 기존부터 있던 구조적 공백이었다.

`schema_review`는 지금까지(review_config.schema 꺼짐 상태에서) `schema_candidates`를 그대로 통과시키는 순수 passthrough였다. 여기에 LLM이 후보 중 질문에 실제 필요한 테이블만 골라내는 closed-set 선택을 추가하고, 그 결과로 `schema_text`까지 재구성하면 EXP-001부터 확인된 낮은 precision(28.4%) 문제를 해결하면서 SQL 생성에도 실제로 영향을 줄 수 있을 것이라는 가설을 세웠다. 이 방향은 EXP-003/004의 "새롭게 배운 것"에서도 다음 후보로 예고된 바 있다.

## 변경 내용

- `server/app/graph/nodes/schema_review.py`: `schema_review_node` 함수를 `make_schema_review_node(llm, schema_provider)` factory로 재작성.
  - review 꺼짐(자동 모드) + 후보 존재 시: `_select_tables()`가 후보 목록(테이블/코멘트/컬럼)을 프롬프트에 넣어 LLM에게 closed-set 선택(`{"selected_tables": [...]}` JSON)을 요청. 후보에 없는 테이블은 필터링, 파싱 실패·빈 응답이면 전체 후보를 그대로 유지하는 fail-safe.
  - review 켜짐(사람 검토) 경로도 포함해, 두 경로 모두 최종 선택 결과로 `schema_provider.get_schema_text(target_tables=selected)`를 다시 호출해 `schema_text`를 재구성해서 반환 — 위에서 발견한 공백을 함께 메움.
  - `full_dump` 모드(후보 없음)일 때는 기존처럼 아무 것도 안 건드림.
- `server/app/graph/build.py`: import를 `make_schema_review_node`로 바꾸고, 이미 만들어져 있던 저비용 고정 모델(`intent_llm`)과 `schema_provider`를 그대로 재사용해 노드 생성.

## 측정 방법

- 비교축(A/B): `schema_review` 순수 passthrough(EXP-001 baseline) vs LLM closed-set 재선정 + `schema_text` 재구성
- 사용한 도구:
  - `eval/execution_accuracy.py` — golden_set 19문항, Execution Accuracy·스키마 매핑 precision/recall/F1 동시 산출
  - `eval/token_cost_comparison.py --compare phase=before,after --experiment EXP-005` — benchmark_queries.json 14문항, 토큰·지연시간·성공률
- 데이터셋: `domains/poc_prostate/golden_set.json`(19문항, execution accuracy용) / `domains/poc_prostate/benchmark_queries.json`(14문항, token_cost_comparison용) — 두 질의셋은 서로 다름(일부만 겹침), 아래 표의 토큰/지연시간 수치를 정답률 수치와 1:1로 대응해서 읽으면 안 됨
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  python eval/token_cost_comparison.py --domain poc_prostate --compare phase=before --experiment EXP-005
  # ...schema_review.py/build.py 변경...
  python eval/token_cost_comparison.py --domain poc_prostate --compare phase=after --experiment EXP-005
  ```

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (golden_set 19문항) | 9/19 (47.4%) | 8/19 (42.1%) | -5.3pp |
| Schema Mapping Precision | 28.4% | 71.1% | +42.7pp |
| Schema Mapping Recall | 90.4% | 64.0% | -26.4pp |
| Schema Mapping F1 | 41.3% | 66.8% | +25.5pp |
| 토큰 사용량 (benchmark 14문항, phase 비교) | 56,136 tok / 41 LLM 호출 | 50,712 tok / 55 LLM 호출 | -5,424 tok(-9.7%), 호출 +14(질문당 재선정 1회) |
| 평균 지연시간 (benchmark 14문항) | 18,356ms (1건 142초 이상치 포함) | 11,631ms | 표면상 감소하지만 아래 한계 참고 — 이상치 제외 시 실제로는 증가 |
| 성공률 (benchmark 14문항, validation/execution 성공 기준) | 92.9% (13/14) | 92.9% (13/14) | 없음 |

## 분석 및 결정

지금까지의 EXP-002~004와 달리 이번엔 "노이즈 범위"라고 보기 어려운 뚜렷한 신호가 나왔다. Schema Mapping F1이 41.3%→66.8%(+25.5pp), precision은 28.4%→71.1%로 두 배 이상 뛰었다 — `schema_text`를 실제로 좁힌 첫 실험이니만큼, EXP-002~004에서 confirmed_schema만 건드리고 schema_text엔 영향이 없어 효과가 미미했던 것과 대조된다.

그런데 정작 이 프로젝트의 진짜 목표 지표인 Execution Accuracy는 47.4%→42.1%(-5.3pp, 19문항 중 1문항)로 떨어졌다. 원인을 11번 질문("처방코드별 검사 건수를 보여줘", 정답 테이블 `poc_prostate_blood` 하나)으로 재현해 확인했다: 벡터 검색 Top-5엔 정답 테이블이 이미 들어있었는데(즉 recall은 이 단계에서 이미 확보돼 있었는데), LLM 재선정이 그걸 버리고 `poc_ssspmordr`(이름이 "처방"류로 읽히는 테이블)를 대신 골랐다 — 실제로 처방코드(`ordr_cd`) 컬럼을 담고 있는 건 `poc_prostate_blood` 쪽인데, 질문의 "처방코드"라는 표면적 어휘에 이끌려 테이블명 유사도로 잘못 판단한 사례다. Schema Mapping Recall이 90.4%→64.0%(-26.4pp)로 크게 떨어진 것도 같은 종류의 오탈락이 다른 질문들에서도 일어났다는 뜻이다.

토큰은 재선정 호출이 하나 늘었는데도 오히려 9.7% 줄었다(schema_text가 좁아져 SQL 생성 프롬프트 자체가 가벼워진 효과가 재선정 호출 비용보다 컸다). 지연시간은 표면적으로는 줄어든 것처럼 보이지만, "변경 전" 평균은 1건의 142초짜리 이상치 때문에 부풀려진 값이다(아래 한계 참고) — 이상치를 빼면 변경 전은 약 8.8초, 변경 후는 11.6초로 재선정 호출 1회만큼(약 30%) 늘어난 게 더 정확한 그림이다.

결론: 이 프로젝트는 EXP-003 때도 "대리 지표(precision/recall)가 좋아져도 headline 지표(F1, 그리고 결국 Execution Accuracy)가 나빠지면 폐기"라는 원칙을 적용했다. 이번엔 대리 지표(Schema Mapping F1)가 큰 폭으로 개선됐지만 진짜 목표 지표(Execution Accuracy)가 나빠지고 지연시간도 늘었으므로, 같은 원칙으로 폐기하고 `schema_review.py`/`build.py`를 원래의 순수 passthrough로 되돌렸다. 다만 원인이 명확하고(표면 어휘 유사도에 낚이는 선택 오류) 고칠 여지가 뚜렷하므로, 완전히 버리기보다 "재선정 프롬프트에 컬럼 내용 기준 판단을 강제하는" 후속 실험의 후보로 남긴다.

## 새롭게 배운 것

- 처음으로 "노이즈가 아닌 뚜렷한 트레이드오프"를 만든 실험이었다 — `schema_text`를 실제로 좁히면 SQL 생성 단계에 진짜 영향이 간다는 게 확인됐다. 거꾸로 말하면 EXP-003·EXP-004가 효과가 미미했던 이유가 "재정렬/컷오프 신호 자체가 약해서"가 아니라 "애초에 SQL 생성 프롬프트에 반영되지 않는 통로(`confirmed_schema`)에서 실험했기 때문"이었을 가능성이 크다는 걸 이번에 알게 됐다.
- LLM 재선정이 "질문 표현과 이름이 비슷한 테이블"에 낚이는 실패 패턴은 EXP-004의 char-bigram 실패와 본질이 같다 — 규칙 기반이든 LLM 기반이든, 표면 어휘 유사도만으로 테이블을 고르면 실제로 그 컬럼이 필요한 값을 담고 있는지와 무관하게 틀릴 수 있다. LLM이라고 이 함정을 자동으로 피하지는 않았다.
- Schema Mapping F1과 Execution Accuracy가 서로 반대 방향으로 크게 움직일 수 있다는 걸 숫자로 처음 봤다(F1 +25.5pp, Execution Accuracy -5.3pp) — 스키마 매핑 지표는 어디까지나 대리 지표이고, 이걸 단독으로 보고 "개선됐다"고 판단하면 실제 목표(정답 SQL 실행)와 반대 방향으로 갈 수 있다. 앞으로는 스키마 매핑 지표만으로 채택 여부를 판단하지 않는다.

## 한계

- `execution_accuracy.py`(golden_set 19문항)와 `token_cost_comparison.py`(benchmark_queries 14문항)는 서로 다른 질의셋이다 — 위 표의 토큰/지연시간 수치를 정답률 변화와 같은 실행 배치의 결과로 보면 안 된다.
- "변경 전" 평균 지연시간(18,356ms)은 질문 1건이 142초 넘게 걸린 이상치 때문에 왜곡됐다 — LLM 게이트웨이 쪽의 일시적 지연/재시도로 추정되며 이번 변경과 무관해 보인다. 이상치를 제외하면 변경 전 평균은 약 8.8초로, 변경 후(11.6초)보다 뚜렷이 빠르다.
- 단일 실행, 반복 없음. Execution Accuracy -5.3pp는 19문항 중 1문항 차이라 표본이 매우 작다 — 다른 질문에서 반대 방향으로 뒤집힐 여지도 있다.
- 후속 아이디어(재선정 프롬프트에 "테이블명 유사도가 아니라 컬럼이 실제로 그 값을 담고 있는지로 판단하라"는 지침 추가, 또는 애매하면 후보를 더 넓게 유지하도록 recall 쪽으로 편향시키는 지침)는 이번 실험에서 시도하지 않았다.
