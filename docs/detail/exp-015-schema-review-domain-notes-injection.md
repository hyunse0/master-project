# EXP-015 schema_review 재선정 프롬프트에 domain_notes 주입

- **날짜**: 2026-09-13
- **상태**: ✅ 채택

## 배경 / 가설

[EXP-014](./exp-014-schema-retrieval-vs-review-bottleneck.md)에서 schema_linking(벡터 검색,
Retrieval Recall 89.3%)과 schema_review(LLM 재선정, Review Retention 76.0%)를 분리 측정한
결과, 병목이 review 단계에 있음을 확인했다. review_miss 6건 중 5건이 전부 동일 패턴 —
`poc_prostate_op`("수술 이력 마트")가 후보에 정상 검색됐는데도 `schema_review`가 이를
탈락시키고 `poc_opsmmsurg`/`poc_ooodrmlop`/`poc_opsmmopcd` 같은 원본 raw 테이블을 대신
선택했다. 코드를 보니 원인이 명확했다 — `schema_review.py`의 재선정 프롬프트
(`_SELECT_PROMPT`)는 `prompt_fragments.yaml`의 domain_notes(마트 우선 규칙 포함)를 전혀
받지 않고 있었다. SQL 생성 프롬프트(`SqlPromptBuilder`)에만 domain_notes가 배선돼 있었던
것 — 이게 [EXP-013](./exp-013-patient-info-mart-note-correction.md)에서 notes를 고쳐도
schema mapping f1이 꿈쩍 안 했던 이유였다.

가설: schema_review의 재선정 프롬프트에도 동일한 domain_notes를 주입하면, 이미 검색된
정답 테이블(`poc_prostate_op`)이 재선정 단계에서 탈락하는 걸 막을 수 있다.

## 변경 내용

- `server/app/graph/nodes/schema_review.py`: `_SELECT_PROMPT`에 `{domain_notes_section}`
  placeholder 추가, `_select_tables()`/`make_schema_review_node()`가 `domain_notes: str`
  파라미터를 받아 프롬프트에 `[도메인 참고사항]` 섹션으로 주입
- `server/app/graph/build.py`: `make_schema_review_node()` 호출 시 이미 로드해둔
  `domain_notes`(SQL 생성 프롬프트에 쓰던 것과 동일 변수)를 그대로 전달

SQL 생성용 notes를 재사용한 것이라 `prompt_fragments.yaml` 자체는 변경하지 않았다(EXP-013
때 patient_info를 이력 마트에서 분리한 내용이 그대로 유효).

## 측정 방법

- 비교축: schema_review 프롬프트에 domain_notes 주입 전 vs 후 (같은 골든셋, notes 내용은
  EXP-013 상태 그대로, 배선 코드만 변경)
- 사용한 도구: `eval/execution_accuracy.py`(정확도) + `eval/schema_recall_diagnostic.py`
  (retrieval/review 병목 재확인, EXP-014에서 만든 신규 진단 스크립트)
- 데이터셋: `domains/poc_prostate/golden_set.json` 전체 23대화/28턴
- "변경 전" 수치는 EXP-013의 "변경 후" 실행과 EXP-014 진단 실행(둘 다 이 실험 직전, 코드
  변경 없이 이어진 상태)을 그대로 재사용 — 별도 재실행 없이 체인으로 연결

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (전체) | 11/28 (39.3%) | 14/28 (50.0%) | **+10.7pp** |
| Execution Accuracy (턴1) | 9/23 (39.1%) | 10/23 (43.5%) | +4.4pp |
| Execution Accuracy (턴2) | 2/4 (50.0%) | 3/4 (75.0%) | +25pp |
| Execution Accuracy (턴3) | 0/1 (0%) | 1/1 (100%) | +100pp (표본 1건) |
| Schema Mapping F1 | 52.5% (p=46.7%, r=66.1%) | 77.5% (p=71.4%, r=93.5%) | **+25.0pp** |
| Condition Summary Faithfulness | 78.3% | 82.6% | +4.3pp |
| retrieval_miss | 3/28 (10.7%) | 3/28 (10.7%) | 0 (미변경 대상) |
| review_miss | 6/28 (21.4%) | 3/28 (10.7%) | **-10.7pp** |
| schema_ok_but_sql_dropped_table | 2/28 (7.1%) | 0/28 (0%) | -7.1pp |
| Review Retention | 76.0% | 88.0% | +12.0pp |
| End-to-end Schema Recall | 67.9% | 78.6% | +10.7pp |

## 분석 및 결정

Execution Accuracy·Schema Mapping F1·Review Retention이 전부 일관되게 개선됐고, retrieval_miss는
손대지 않은 대로 그대로였다 — EXP-014의 진단(병목이 review 단계)과 정확히 일치하는
결과라 인과관계가 명확하다. `schema_ok_but_sql_dropped_table`이 2건에서 0건이 된 것도
같은 domain_notes가 이제 review 단계에서 먼저 올바른 테이블을 확정해준 덕에 생성 단계의
혼동까지 같이 줄어든 것으로 보인다. 채택.

## 새롭게 배운 것

- EXP-013(SQL 생성 프롬프트 수정, 효과 없음)과 EXP-015(schema_review 프롬프트 수정, 큰
  효과)가 "같은 domain_notes 내용을 어느 파이프라인 단계에 배선하느냐"만 다른 실험인데
  결과가 극명하게 갈렸다 — 프롬프트 내용의 정확성보다 "그 내용이 실제로 필요한 단계에
  도달하는가"가 더 중요할 수 있다는 걸 보여주는 사례.
- EXP-011이 "후보를 늘리면 역효과"였던 것과 달리, 이번엔 후보 풀(retrieval)은 전혀
  건드리지 않고 review의 판단 근거만 보강했더니 부작용 없이 개선됐다 — 스키마 단계
  개선은 "후보를 얼마나 주는가"보다 "재선정이 그 후보를 갖고 뭘 판단하는가"가 레버리지가
  더 크다.
- 표본이 작은데도(턴2 n=4, 턴3 n=1) 멀티턴 정확도가 크게 뛴 것은, 멀티턴 후속 질문이
  직전 턴에서 확정된 스키마를 이어받는 구조라 스키마 확정 단계의 개선 효과가 후속 턴에서
  누적되기 때문으로 보인다(1턴짜리 개선이 다턴 대화에서 복리로 반영됨).

## 한계

- 표본이 작다(28턴, 그중 턴2 4건·턴3 1건). retrieval_miss 3건(복잡한 3-테이블 질문)은
  이번 실험 범위 밖으로 남아있다 — 다음 병목.
- domain_notes를 두 프롬프트(SQL 생성, schema_review)에 동일하게 주입하는 방식이라,
  두 단계에 서로 다른/상충하는 지침이 필요해지는 경우엔 이 배선 방식을 재검토해야 한다.
