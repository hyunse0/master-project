# EXP-014 Schema Retrieval Recall과 Schema Review Retention의 병목 분리

- **날짜**: 2026-09-13
- **상태**: 📝 정성적 관찰 (코드 변경 없는 진단 실행 — 다음 실험(EXP-015)의 근거 자료)

## 배경 / 가설

[EXP-013](./exp-013-patient-info-mart-note-correction.md)에서 "SQL 생성 프롬프트 notes를
고쳐도 schema mapping f1이 전혀 안 바뀐다"는 걸 확인했지만, 이것만으론 병목이
`schema_linking`(벡터 검색)에 있는지 `schema_review`(LLM 재선정)에 있는지 구분이 안 됐다.
[EXP-011](./exp-011-schema-candidate-expansion.md)이 "후보를 top-5→8로 늘렸더니 오히려
정확도가 떨어졌다"는 결과도 retrieval recall 개선과 review 재선정 품질 저하가 뒤섞인
실험이라 어느 쪽 문제인지 분리하지 못했다.

가설: 정답 테이블이 최종 `confirmed_schema`에 없는 경우를 (1) `schema_candidates`(review
이전, 벡터 검색 top-5)에도 없는 경우(retrieval 문제)와 (2) candidates엔 있는데
`confirmed_schema`(review 이후)에서 탈락한 경우(review 문제)로 나누면, 다음 실험을
retrieval 개선과 review 개선 중 어느 쪽에 투자할지 데이터로 결정할 수 있다.

## 변경 내용

코드 변경 없음 — 관찰만 하는 진단 스크립트 `server/eval/schema_recall_diagnostic.py`를
새로 작성. golden_set.json 28턴 전체에 대해 `graph.invoke()`를 1회씩 실행하고
`expected_sql`에서 뽑은 gold_tables를 `state["schema_candidates"]`(retrieval 결과) /
`state["confirmed_schema"]`(review 이후) / 생성된 SQL이 실제로 참조한 테이블과 비교해
턴마다 4가지 중 하나로 분류한다: `retrieval_miss` / `review_miss` /
`schema_ok_but_sql_dropped_table` / `schema_ok`.

초기 실행에서 `expected_sql`의 WITH절 CTE 별칭(`counts`, `ratios`)을 sqlglot이 실제
테이블로 잘못 집계하는 버그를 발견해 수정(CTE 별칭 목록을 뽑아 제외) — 이 버그가 있으면
CTE를 쓰는 golden_set 문항이 항상 retrieval_miss로 오분류된다. 이 버그는
`eval/execution_accuracy.py`의 동일한 `_extract_tables` 로직에도 있어 schema mapping f1이
CTE 사용 문항에서 과소평가돼 왔을 가능성이 있음(별도 확인 필요, 이번 실험 범위 밖).

## 측정 방법

- 비교축: 없음(진단 전용, A/B 아님)
- 사용한 도구: `eval/schema_recall_diagnostic.py`(신규)
- 데이터셋: `domains/poc_prostate/golden_set.json` 전체 23대화/28턴
- 재현 명령어: `python eval/schema_recall_diagnostic.py --domain poc_prostate --verbose`

## 결과

| 지표 | 값 |
|---|---|
| retrieval_miss | 3/28 (10.7%) |
| review_miss | 6/28 (21.4%) |
| schema_ok | 17/28 (60.7%) |
| schema_ok_but_sql_dropped_table | 2/28 (7.1%) |
| Retrieval Recall (gold ⊆ schema_candidates) | 89.3% |
| Review Retention (retrieved gold 중 review 이후 유지 비율) | 76.0% |
| End-to-end Schema Recall (gold ⊆ confirmed_schema) | 67.9% |

review_miss 6건 중 5건(conv5/7/13/20턴2/21턴1)이 전부 동일한 패턴: `poc_prostate_op`
("수술 이력 마트")가 `schema_candidates`엔 정상적으로 들어왔는데 `schema_review`가 이걸
탈락시키고 `poc_opsmmsurg`("수술일정기본") / `poc_ooodrmlop`("치료처방수술매핑내역") /
`poc_opsmmopcd`("수술전후수술명기본") 같은 원본 raw 테이블을 대신 선택했다. 우연이 아니라
반복 재현되는 오선택이다.

## 분석 및 결정

Retrieval Recall(89.3%)이 Review Retention(76.0%)보다 뚜렷이 높다 — `schema_linking`의
벡터 검색은 이미 잘 작동하고 있고, 병목은 `schema_review`의 LLM 재선정 단계다.

원인을 코드에서 확인: `schema_review.py`의 `_SELECT_PROMPT`는 `question`/`intent`/후보
목록만 받고 `prompt_fragments.yaml`의 도메인 노트(마트 우선 규칙 포함)를 전혀 받지 않는다
— SQL 생성 프롬프트(`SqlPromptBuilder`)에만 domain_notes가 주입되고, 정작 테이블을
좁히는 `schema_review`는 그 규칙을 모른 채 판단하고 있었다. EXP-013에서 "notes를 고쳐도
schema mapping f1이 안 바뀐 이유"가 여기서 설명된다 — review 단계는애초에 그 notes를
본 적이 없다.

schema_ok_but_sql_dropped_table 2건도 같은 계열 — confirmed_schema에 `poc_prostate_op`가
이미 있었는데도 SQL 생성이 `poc_opsmmsurg`를 썼다. 마트/원본 혼동이 review 단계뿐 아니라
생성 단계에도 일부 남아있다는 뜻이나, 이번 실험은 review 단계 병목이 더 크고(6건 vs 2건)
더 명확한 단일 원인(domain_notes 미주입)을 갖고 있어 EXP-015에서 이것부터 고친다.

## 새롭게 배운 것

- schema_linking(벡터 검색)과 schema_review(LLM 재선정)는 서로 다른 실패 모드를 가지며,
  둘을 한 실험에서 동시에 바꾸면(EXP-011처럼) 기여도를 분리할 수 없다 — 앞으로 스키마
  단계 실험은 항상 이 둘을 분리해서 설계해야 한다.
- `prompt_fragments.yaml`의 domain_notes는 그래프 전체에 자동으로 퍼지는 게 아니라
  `SqlPromptBuilder`(SQL 생성)에만 명시적으로 연결돼 있었다 — 새 노드를 추가하거나 기존
  노드에 도메인 지식이 필요해지면 "notes가 이미 있으니 자동으로 반영되겠지"라고 가정하면
  안 되고 매번 명시적으로 배선해야 한다.
- 같은 "마트 vs 원본 테이블" 혼동이 review 단계(6건)와 생성 단계(2건) 양쪽에서 관찰됐다
  — 하나의 도메인 지식 격차가 파이프라인 여러 단계에 동시에 새는 경우가 있다는 것.
- golden_set.json의 CTE 기반 문항에서 `_extract_tables`가 CTE 별칭을 테이블로
  오인식하는 버그를 발견 — `execution_accuracy.py`의 schema mapping f1에도 같은 버그가
  있어 과거 실험(EXP-003~013)의 f1 수치가 CTE 사용 문항(2문항)에서 아주 소폭 과소평가됐을
  수 있다(정확도 자체는 실행 결과 비교라 영향 없음).

## 한계

- 표본 28턴(그중 CTE 사용 문항 2개)으로 매우 작다 — review_miss 5건이 같은 패턴이라는 건
  강한 신호지만 다른 도메인/골든셋에서는 다른 혼동 쌍이 나올 수 있다.
- `schema_ok_but_sql_dropped_table` 분류는 "SQL이 gold_tables를 전부 참조하는가"만
  보므로, gold보다 많은 테이블을 참조하며 그중 gold도 포함된 경우까지는 세밀하게
  구분하지 않는다.
