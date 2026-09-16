# EXP-013 patient_info를 이력 마트 우선순위 규칙에서 분리 + 원천 테이블 JOIN 유도 노트 추가

- **날짜**: 2026-09-13
- **상태**: ❌ 폐기 (가설 기각, 노트 자체는 사실관계상 맞아 파일에는 유지)

## 배경 / 가설

골든셋 오답 15건(28턴 중)을 직접 diff해 원인을 분류한 결과, "조인 누락"으로 분류된 4건 중 2건
(연령대별 수술 종류, 호르몬 치료 처방 여부)이 `poc_prostate_patient_info`의 치료 관련 스냅샷 컬럼
(`op_nm`, `treat_desc_hormon`)을 직접 사용하고 원천 이력 테이블(`poc_prostate_op`,
`poc_ooodmordr`)과의 JOIN을 생략한 패턴임을 확인했다.

DB를 직접 조회해보니:
- `patient_info.op_nm`: 100건 중 30건 NULL, 나머지 70건은 `poc_prostate_op.inhosp_op_eng_nm`과
  동일값 — 불완전한 스냅샷
- `patient_info.treat_desc_hormon`: 100건 전부 NULL — 항상 비어 있는 죽은 컬럼. 호르몬 치료
  여부는 `poc_ooodmordr`(ADT001/ADT002)에서만 확인 가능

그런데 기존 `prompt_fragments.yaml`엔 "분석 마트 4개(`patient_info/op/path/blood`)를 원천보다
우선, 원천과 JOIN하지 마라"는 규칙이 이미 있었다 — `patient_info`를 나머지 3개(진짜 이력 마트)와
동일하게 취급한 게 원인이라고 보고, `patient_info`를 이 규칙에서 분리하면 위 2건이 고쳐질
것이라 가설을 세웠다.

## 변경 내용

`server/domains/poc_prostate/prompt_fragments.yaml`의 notes 중 마트 우선순위 규칙을 수정:
- 이력 마트 3개(`poc_prostate_op/path/blood`)만 "원천보다 우선"으로 남기고
- `poc_prostate_patient_info`는 이력 마트가 아니라 결측 있는 요약 코호트 테이블임을 명시,
  치료 상세 조건은 스냅샷 컬럼 대신 원천 이력 테이블과 `s_patno`로 JOIN하라고 별도 문장 추가

## 측정 방법

- 비교축(A/B): yaml notes 수정 전 vs 후 (같은 골든셋, 같은 코드, notes 텍스트만 변경)
- 사용한 도구: `eval/execution_accuracy.py`
- 데이터셋: `domains/poc_prostate/golden_set.json` 전체 23대화/28턴
- 재현 명령어: `python eval/execution_accuracy.py --domain poc_prostate`

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (전체) | 10/28 (35.7%) | 11/28 (39.3%) | +3.6pp |
| Execution Accuracy (턴1, n=23) | 9/23 (39.1%) | 9/23 (39.1%) | 0 |
| Execution Accuracy (턴2, n=4) | 1/4 (25.0%) | 2/4 (50.0%) | +25pp (표본 4건) |
| Schema Mapping F1 | 52.6% (p=45.2%, r=72.0%) | 52.5% (p=46.7%, r=66.1%) | -0.1pp |
| Condition Summary Faithfulness | 78.3% | 78.3% | 0 |
| 타겟 문항 "연령대별 수술 종류" schema f1 | 0.3333 | 0.3333 | 0 |
| 타겟 문항 "호르몬 처방" schema f1 | 0.6667 | 0.6667 | 0 |

타겟 문항 2건의 생성 SQL을 직접 비교한 결과, 변경 전후로 거의 동일 — "연령대별 수술 종류"는
수정 후에도 여전히 `poc_prostate_patient_info.op_nm`을 그대로 사용했다. 전체 정답률이 소폭
오른 건(+1건) 타겟과 무관한 멀티턴 후행 질문(턴3, "그 환자들 병기 분포도 보여줘")에서였다.

## 분석 및 결정

타겟 문항의 schema mapping f1이 소수점까지 완전히 동일하다는 게 핵심 증거다 — 이는
`schema_linking` 단계가 산출하는 `confirmed_schema`(SQL 생성에 실제로 넘어가는 후보 테이블 집합)가
notes 변경 전후로 전혀 달라지지 않았다는 뜻이다. `poc_prostate_op`/`poc_ooodmordr`가 애초에
후보에 없었다면, SQL 생성 프롬프트의 notes를 아무리 정확하게 고쳐도 모델이 존재하지도 않는
후보를 join할 수는 없다. 즉 가설이 틀렸다 — 문제는 SQL 생성 단계의 지침 부재가 아니라
schema_linking의 테이블 후보 검색/포함 로직에 있다.

노트 자체(마트 3개 vs patient_info 스냅샷 컬럼의 결측 사실)는 틀린 내용이 아니므로 파일에는
그대로 남겨두기로 했다(사용자 결정, 2026-09-13) — 다만 이 실험이 목표했던 정확도 개선 효과는
없었으므로 가설은 폐기한다.

## 새롭게 배운 것

- `prompt_fragments.yaml`의 notes는 SQL 생성 프롬프트(`app/sql/prompt_builder.py`)에만
  주입되고 `schema_linking` 노드의 검색 쿼리/스코어링에는 전혀 관여하지 않는다 — 스키마
  검색 단계의 문제는 SQL 생성 단계 프롬프트 수정으로 우회할 수 없다.
- "조인 누락"으로 보였던 오답이 실제로는 두 단계로 나뉜다: (1) schema_linking이 필요한
  테이블을 후보에 못 넣는 경우, (2) 후보엔 있는데 생성 단계에서 안 쓰는 경우. 이번 2건은
  전부 (1)에 해당했다 — f1이 그대로라는 게 그 증거. (2) 유형인지 확인하려면 confirmed_schema
  자체를 로그에 남겨 직접 대조해야 한다(현재는 schema mapping f1만 남고 confirmed_schema
  테이블 목록 자체는 golden run 로그에 노출 안 됨).
- EXP-011(top-N/FK 확장)이 이미 "후보를 무작정 늘리면 schema_review 재선정 품질이
  떨어진다"로 폐기됐던 것과 종합하면, 다음 시도는 "후보를 더 많이"가 아니라 "이 질문엔
  왜 정확히 이 테이블이 후보에서 빠졌는가"를 임베딩 유사도 점수 단위로 먼저 봐야 한다.

## 한계

- 표본이 작다(타겟 문항 2건, 전체 골든셋 28턴). LLM 비결정성으로 턴2/3의 미세한 변동은
  신호로 보기 어렵다.
- confirmed_schema의 실제 테이블 목록을 로그에서 직접 못 봐서, "후보에 아예 없었다"는
  결론을 f1 수치로 간접 추정했다 — 직접 대조는 아니다.
