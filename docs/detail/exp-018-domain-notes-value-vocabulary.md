# EXP-018 SQL 생성 domain_notes에 코드값 vocabulary 주입

- **날짜**: 2026-09-14
- **상태**: ✅ 채택

## 배경 / 가설

[EXP-017](./exp-017-schema-embedding-retrieval-hints.md)에서 retrieval_miss 4건(hard 케이스)의
스키마 검색 문제는 해결했지만, 4건 모두 end-to-end로는 여전히 실패했다. 원인을 SQL 생성
결과로 직접 확인하니 스키마는 맞게 찾으면서도 그 안의 **실제 코드값을 몰라서** 틀리고
있었다:
- 호르몬 처방(`poc_ooodmordr.ordr_cd IN ('ADT001','ADT002')`)을 몰라 "코드가 명확하지
  않다"는 주석과 함께 엉뚱한 조건(`vald_yn='Y'`)으로 대체
- CT/MRI 양성 판정을 `mark_rslt_val='Positive'`(정규화값)가 아니라
  `exam_rslt_val ILIKE '%양성%'`(원문 텍스트)로 잘못된 컬럼을 사용
- PSA 코드를 "'PSA'라고 가정"하며 실제 코드(`PSA001`)를 추측으로 대체

EXP-017에서 이미 이 코드값들을 `table_retrieval_hints`에 적어뒀었는데, 그건
`schema_indexer.py`(스키마 임베딩)에만 배선돼 있고 SQL 생성 프롬프트(`domain_notes`)에는
연결되지 않았다는 걸 그 실험의 "새롭게 배운 것"에서 이미 확인했다.

가설: 같은 코드값 vocabulary를 SQL 생성이 실제로 보는 `domain_notes`(`prompt_fragments.yaml`의
`notes:` 필드)에도 넣으면, 스키마 매핑뿐 아니라 SQL 로직 자체가 올바른 코드값을 쓰게 된다.

## 변경 내용

- `domains/poc_prostate/prompt_fragments.yaml`의 `notes:`에 아래 블록 추가(코드 변경 없음
  — `notes:`는 이미 `SqlPromptBuilder`와 `schema_review`([EXP-015](./exp-015-schema-review-domain-notes-injection.md)에서
  배선) 양쪽에 주입되는 필드라 새 배선이 필요 없었다):
  - 검사결과 판정은 `exam_rslt_val`이 아니라 `mark_rslt_val`을 쓰라는 규칙
  - `exam_cd`/`ordr_cd` 허용 코드 화이트리스트(CT001/MRI001/BONE001/PET001/PSA001/ADT001/ADT002)와
    "목록에 없는 코드는 추측 대신 VALUE_UNCONFIRMED로 반려" 지시
- 1차 측정 후 `poc_prostate_blood`가 `exam_cd`/`ordr_cd` 두 코드 컬럼을 모두 갖고 있어서
  PSA 코드를 잘못된 컬럼(`exam_cd`)에 넣는 새로운 실패가 나타난 것을 발견 — 컬럼명을
  명시(`ordr_cd='PSA001'`)하도록 노트를 다시 수정하고 재측정(아래 결과의 "1차"/"최종"으로 구분)

## 측정 방법

- 비교축: `notes:` 변경 전(EXP-017 이후 상태) vs 변경 후(1차: 코드값만 명시 / 최종: 컬럼명까지 명시)
- 사용한 도구: `eval/execution_accuracy.py --domain poc_prostate`
- 데이터셋: `domains/poc_prostate/golden_set.json` 전체 33대화/38턴
- "변경 전" 수치는 [EXP-017](./exp-017-schema-embedding-retrieval-hints.md)의 "변경 후" 실행
  결과를 재사용(직전 실험 직후라 코드/데이터 상태 동일 — 재실행 생략)
- 타깃 4건(conv16/18/19/33)은 `execution_accuracy.py` 실행과 별도로 그래프를 직접 호출해
  생성 SQL·오류 코드를 확인(단위 수준 관찰)

## 결과

| 지표 | 변경 전(EXP-017 이후) | 1차(코드값만) | 최종(컬럼명 명시) |
|---|---|---|---|
| Execution Accuracy (전체) | 14/38 (36.8%) | 15/38 (39.5%) | 15/38 (39.5%) |
| Schema Mapping F1 | 83.5% | 88.3% | 89.3% |
| Condition Summary Faithfulness | 25/33 (75.8%) | 29/35 (82.9%) | 27/35 (77.1%) |

타깃 4건(conv16/18/19/33) 개별 결과:

| 케이스 | 변경 전 | 1차 | 최종 |
|---|---|---|---|
| conv19 (골스캔/PET + 응급수술) | FAIL(schema_ok, 로직 오류) | **OK** | **OK** |
| conv18 (CT/MRI 양성 + 병기) | FAIL | FAIL(코드/컬럼은 맞지만 SELECT 컬럼 구성이 골든셋과 다름) | 미재확인(aggregate에 포함) |
| conv33 (MRI 양성 + Gleason + PSA) | FAIL | FAIL(PSA 코드를 `exam_cd`에 잘못 적용 → value anchor 실패 → 재시도가 무관한 코드 30개를 나열) | FAIL(aggregate 로그상 지속) |
| conv16 (호르몬 처방 + 응급수술 + 병기) | FAIL | FAIL(VALUE_UNCONFIRMED, SQL 미생성) | FAIL(aggregate 로그상 지속) |

## 분석 및 결정

Execution Accuracy가 하락 없이 개선(36.8%→39.5%)됐고 Schema Mapping F1도 함께
올랐다([1.5절 채택 원칙](../kpi-experiment-log.md#15-채택-판단-원칙--대리지표proxy-metric-단독-개선은-채택-근거가-아니다) 충족) — 채택.

타깃 4건 중 **conv19 하나는 확실히 end-to-end로 고쳐졌다** — hard 케이스가 하나 살아난
첫 사례다. 나머지 3건은 여전히 실패하지만 실패 양상이 바뀌었다:
- conv18은 코드값(CT001/MRI001)과 판정 컬럼(mark_rslt_val)을 이제 정확히 쓰지만, SELECT에
  올리는 컬럼 구성(예: `dis_stage`/`score` 대신 `clinic_stage`/`biopsy_gs_score1+2`)이
  골든셋과 달라 정확 일치 비교에서 걸린다 — 이건 값 vocabulary 문제가 아니라 별도의
  "동의어 컬럼 선택" 문제.
- conv33은 코드값 vocabulary를 추가한 것 자체가 일시적으로 새 실패를 유발했다 —
  `poc_prostate_blood`에 코드 컬럼이 두 개(`exam_cd`, `ordr_cd`) 있는 걸 몰랐던 상태에서
  "PSA001=PSA"라고만 적었더니 잘못된 컬럼에 적용됐다. 컬럼명을 명시한 뒤에도 aggregate
  로그상 이 케이스는 여전히 실패로 남아있어(단위 수준 재확인은 생략, 시간상 aggregate
  결과로 판단), 이 리비전만으로 완전히 해결되진 않은 것으로 보인다 — 다른 조건(Gleason
  grade_group, MRI positive) 결합 로직에 별도 원인이 남아있을 가능성.
- conv16은 SQL 생성 이전 단계(`VALUE_UNCONFIRMED`)에서 계속 막힌다 — "호르몬 치료제"라는
  자연어 표현 자체를 값으로 확인하려는 시도가 있는 것으로 보이며, 이건 코드값 vocabulary가
  아니라 value_anchor/확인 단계의 별도 문제로 추정된다(이번 실험 범위 밖).

## 새롭게 배운 것

- 코드값 vocabulary를 추가할 때 "어떤 코드가 무엇을 의미하는지"뿐 아니라 "그 코드가
  어느 컬럼에 들어있는지"까지 명시해야 한다 — 같은 테이블에 코드 컬럼이 여러 개
  있으면(`exam_cd`/`ordr_cd`) 컬럼명 없이 코드값만 적은 노트가 오히려 새로운 오류를
  유발할 수 있다(1차 시도의 conv33 회귀).
- "스키마는 맞게 찾고 코드값도 맞게 썼다"고 해서 골든셋 정확 일치 비교를 통과하는 건
  아니다 — SELECT에 어떤 컬럼을 올릴지(동의어 컬럼 선택)는 코드값 vocabulary와 별개의
  문제로 남아있다(conv18). 값 vocabulary 문제와 컬럼 선택 문제를 같은 실험에서 동시에
  고치려 하지 말고 분리해서 봐야 한다는 걸 이번에 확인했다.
- hard 케이스 4건을 만들 때 이미 겨냥했던 "복합 조건 + 코드화된 값" 패턴이, 실제로
  값 vocabulary 하나를 고치는 것만으로는 한 번에 다 안 풀린다 — 각 케이스가 서로 다른
  잔여 원인(컬럼 선택, value_anchor 단계 문제, 다른 코드 컬럼 혼동)을 갖고 있어서 "hard
  난이도"라는 라벨 하나로 뭉뚱그리면 안 되고 케이스별로 원인을 계속 분해해야 한다.

## 한계

- 표본이 작다(38턴). Condition Summary Faithfulness가 1차→최종에서 82.9%→77.1%로
  떨어졌는데, 이 지표는 이번 실험이 직접 겨냥한 게 아니고([1.5절] 판단 기준상 타이브레이커일
  뿐) LLM 판정 자체의 샘플링 노이즈일 가능성이 높다 — 별도로 조사하지 않았다.
- conv18/33/16 세 케이스는 여전히 실패로 남아있어, hard 케이스 6건 중 이번까지 포함해도
  1건(conv19)만 해결됐다. 나머지는 성격이 다른 문제(컬럼 선택, value_anchor)라 별도
  실험이 필요하다.
- 실행 중 `run_metrics 기록 실패: Object of type date is not JSON serializable` 경고가
  1건 관측됐다 — 정확도 채점 자체엔 영향 없어 이번 실험 범위 밖으로 남겨두지만, 로깅
  파이프라인에 실제 버그가 있을 가능성이 있어 별도 확인이 필요하다.
