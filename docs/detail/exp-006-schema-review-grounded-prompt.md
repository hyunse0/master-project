# EXP-006 schema_review LLM 재선정 — 컬럼 근거 강제 프롬프트 + 캐시 기반 schema_text 조립

- **날짜**: 2026-09-01
- **상태**: ✅ 채택

## 배경 / 가설

EXP-005(`schema_review`에 LLM 재선정 + `schema_text` 재구성)는 Schema Mapping F1을 41.3%→66.8%(+25.5pp)까지 올렸지만 Execution Accuracy가 47.4%→42.1%(-5.3pp)로 떨어져 폐기했다. 원인을 11번 질문("처방코드별 검사 건수를 보여줘")으로 재현했더니, 벡터 검색 Top-5엔 정답 테이블(`poc_prostate_blood`)이 이미 있었는데 LLM이 이름이 "처방"류로 읽히는 다른 테이블(`poc_ssspmordr`)을 대신 골랐다 — 이를 "테이블명 표면 유사도에 낚인 오류"로 진단하고, (a) 선택 프롬프트에 "테이블명이 아니라 실제 컬럼 내용을 근거로 판단하라"는 지침과 "애매하면 포함하라"는 recall 편향 지침을 추가하면 이런 오탈락이 줄어들 것이고, (b) `schema_review`가 매번 `schema_provider.get_schema_text()`로 DB를 다시 introspect하던 중복 조회(EXP-005 때 `schema_linking`과 `schema_review` 양쪽에서 전체 테이블을 재조회, 테이블당 3쿼리씩)를 `schema_candidate_details`에 이미 있는 캐시(`text` 필드, Qdrant 색인 시점에 만들어둔 테이블 렌더링)로 대체하면 불필요한 DB 부하 없이 같은 결과를 낼 수 있을 것이라는 가설을 세웠다.

재현 스크립트로 11번 질문을 다시 돌려본 결과, 두 후보 테이블(`poc_ssspmordr`, `poc_prostate_blood`)이 **둘 다 실제로 `ordr_cd`(처방코드) 컬럼을 갖고 있어서** 애초에 스키마 텍스트만으로는 구분 불가능한 진짜 애매한 케이스였다는 게 드러났다 — "컬럼 근거 강제" 지침으로는 이 특정 케이스는 못 고칠 걸로 예상됐지만, EXP-005에서 recall이 90.4%→64.0%로 크게 떨어진 건 이 질문 하나 때문이 아니라 여러 질문에 걸친 문제였으므로, 다른 케이스들에는 프롬프트 보강이 도움이 될 수 있다고 보고 실험을 그대로 진행했다.

## 변경 내용

- `server/app/graph/nodes/schema_linking.py`: `schema_candidate_details`의 각 항목에 `"text"`(Qdrant payload의 테이블 전체 렌더링, `schema_indexer.py`가 색인 시점에 이미 만들어둔 값) 필드를 추가.
- `server/app/graph/state.py`: `schema_candidate_details`의 shape 주석을 `[{table, comment, score, columns}]` → `[{table, comment, score, columns, text}]`로 갱신.
- `server/app/graph/nodes/schema_review.py`: EXP-005 코드를 되살리되 두 가지를 바꿈:
  - **선택 프롬프트 보강**: (1) "테이블명/코멘트가 아니라 실제로 질문이 요구하는 값을 담은 컬럼이 있는지로 판단하라"는 지침, (2) "포함할지 애매하면 포함하라(recall 편향)"는 지침을 추가. 응답 형식도 "각 후보에 대해 포함 여부와 근거를 한 줄씩 적은 뒤 마지막 줄에 JSON만" 방식으로 바꿔 근거를 먼저 쓰게 강제(`_parse_selected_tables`가 정규식으로 마지막 JSON 블록만 추출).
  - **schema_text 조립을 캐시 기반으로 전환**: `_assemble_from_cache()`가 `confirmed_schema`로 선택된 테이블들을 `schema_candidate_details[].text`에서 찾아 이어붙인다. 선택된 테이블이 캐시에 없는 예외적인 경우(예: 사람이 후보 밖 테이블을 직접 추가)에만 `schema_provider.get_schema_text()`로 DB 폴백. `_select_tables`에 넘기는 후보 설명도 압축 포맷 대신 `text`(전체 렌더링: 컬럼 타입·PK·FK 포함)를 그대로 사용해 판단 근거를 풍부하게 함.
- `server/app/graph/build.py`: `make_schema_review_node(intent_llm, schema_provider)`로 다시 연결(EXP-005와 동일한 저비용 고정 모델 재사용).

## 측정 방법

- 비교축(A/B): `schema_review` 순수 passthrough(baseline, EXP-005의 phase=before와 동일 코드) vs 컬럼 근거 강제 + recall 편향 프롬프트 + 캐시 기반 재선정
- 사용한 도구:
  - `eval/execution_accuracy.py` — golden_set 19문항
  - `eval/token_cost_comparison.py --compare phase=after --experiment EXP-006` — benchmark_queries.json 14문항. "before" 값은 EXP-005의 `phase=before --experiment EXP-005` 실행분을 그대로 재사용했다(같은 baseline 코드에서 잰 값이고, 그 사이 `schema_review.py`/`schema_linking.py` 외 관련 코드가 바뀌지 않았음을 git 상태로 확인).
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  python eval/token_cost_comparison.py --domain poc_prostate --compare phase=after --experiment EXP-006
  ```

## 결과

| 지표 | 변경 전 (baseline) | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (golden_set 19문항) | 9/19 (47.4%) | 9/19 (47.4%) | 없음 |
| Schema Mapping Precision | 28.4% | 48.7% | +20.3pp |
| Schema Mapping Recall | 90.4% | 72.8% | -17.6pp |
| Schema Mapping F1 | 41.3% | 55.2% | +13.9pp |
| 토큰 사용량 (benchmark 14문항) | 56,136 tok / 41 LLM 호출 | 82,171 tok / 55 LLM 호출 | +26,035 tok(+46.4%), 호출 +14(질문당 재선정 1회) |
| 평균 지연시간 (benchmark 14문항, 이상치 제외 추정) | 약 8.8초 | 약 11.0초 | 약 +25% |
| 성공률 (benchmark 14문항, validation/execution 성공 기준) | 92.9% (13/14) | 92.9% (13/14) | 없음 |

## 분석 및 결정

11번 질문("처방코드별 검사 건수")은 예상대로 이번에도 실패했다 — 재현 확인 결과 두 후보 테이블 모두 실제로 "처방코드" 컬럼을 갖고 있어서, 스키마 텍스트만으로는 어느 쪽이 golden_set이 의도한 "정답" 테이블인지 원천적으로 판단 불가능한 케이스였다(정답은 이 PoC 도메인에서 실제 쓰는 마트 테이블이 무엇인지에 대한 데이터 큐레이션 지식이지, 스키마에서 추론 가능한 정보가 아니다). 컬럼 근거 강제 프롬프트로 고칠 수 있는 종류의 오류가 아니었다.

다만 golden_set 19문항 전체로 보면 Execution Accuracy는 9/19로 baseline과 완전히 동일했다 — 문항 구성은 바뀌었다(10번 "혈액검사 코드별 검사 건수"가 새로 성공, 11번이 대신 실패) — Execution Accuracy 총량은 유지하면서 Schema Mapping F1은 41.3%→55.2%(+13.9pp)로 뚜렷이 개선됐다. EXP-005(precision 71.1%/recall 64.0%, 공격적으로 후보를 좁힘)보다는 덜 극단적인 precision/recall 지점(48.7%/72.8%)에 자리잡았는데, recall 편향 지침이 의도대로 작동해 EXP-005보다 후보를 덜 공격적으로 쳐낸 결과로 보인다.

비용 쪽은 트레이드오프가 있다: 토큰이 56,136→82,171(+46.4%)로 늘었다. EXP-005는 선택 프롬프트가 짧고(압축 포맷) 후보를 더 공격적으로 줄여 최종 `schema_text`가 작아진 덕에 순 토큰이 오히려 줄었는데(-9.7%), EXP-006은 (1) 선택 프롬프트 자체가 압축 포맷 대신 전체 테이블 렌더링(`text`, 컬럼 타입·FK 포함)을 후보마다 통째로 넣고, (2) "근거를 한 줄씩 적은 뒤 JSON" 방식이라 출력 토큰도 늘고, (3) recall 편향으로 후보를 덜 쳐내 최종 `schema_text`도 EXP-005만큼 작아지지 않아서, 세 요인이 겹쳐 토큰이 오히려 늘었다. 지연시간도 이상치를 제외하면 약 8.8초→11.0초(+25%)로, 재선정 호출 1회가 그대로 더해진 정도다.

정리하면 이번 실험은 "진짜 지표(Execution Accuracy)는 그대로, 대리 지표(Schema Mapping F1)는 뚜렷이 개선, 그 대가로 토큰·지연시간이 유의미하게 증가"라는 트레이드오프였다. EXP-002~005와 달리 처음으로 Execution Accuracy를 깎지 않으면서 실질적인 개선을 낸 사례라, 이 트레이드오프를 감수할 가치가 있다고 보고 채택했다(사용자 확인 후 코드 유지).

## 새롭게 배운 것

- **"컬럼 근거를 요구하면 표면 유사도 오류가 줄어든다"는 가설이 검증한 실제 사례는 없었다** — 유일하게 재현 확인한 실패 케이스(#11)는 애초에 두 후보 모두 정답 컬럼을 진짜로 갖고 있는, 스키마만으로는 원천적으로 풀 수 없는 애매한 케이스였다. 이건 "LLM이 틀렸다"가 아니라 "골든셋의 정답이 스키마 밖의 도메인 지식(어떤 테이블이 실제 운영 마트인지)에 의존한다"는 걸 보여준다 — 이런 유형의 오류는 프롬프트를 아무리 고쳐도 스키마 텍스트만으로는 근본적으로 해결이 안 된다.
- 그럼에도 골든셋 전체로는 Execution Accuracy가 유지되고 F1은 올랐다 — 즉 프롬프트 보강이 "진단했던 그 케이스"는 못 고쳤지만 "진단하지 않았던 다른 케이스들"에서 recall을 회복시키는 효과는 있었다는 뜻이다. 사후에 재현한 단일 사례로 전체 효과를 예단하면 안 된다는 걸 다시 확인했다.
- **"판단 근거를 풍부하게 준다"와 "토큰을 아낀다"는 이번엔 반대 방향으로 작용했다** — EXP-005는 압축 포맷 덕에 토큰이 줄었는데, EXP-006은 판단 품질을 위해 후보 설명을 전체 렌더링으로 늘리고 추론 과정까지 출력시키면서 토큰이 46% 늘었다. 다음에 비용을 줄이고 싶다면 "판단 근거 자체를 늘리는" 방향이 아니라 다른 지점(예: 후보 설명은 압축 포맷 유지하되 recall 편향 지침만 남기는 조합)을 시도해볼 여지가 있다 — 이번 실험은 그 조합을 분리 검증하지 않았다.

## 한계

- `execution_accuracy.py`(golden_set 19문항)와 `token_cost_comparison.py`(benchmark_queries 14문항)는 서로 다른 질의셋이다 — 토큰/지연시간 수치를 정답률 변화와 같은 실행 배치의 결과로 보면 안 된다.
- "변경 전" 토큰/지연시간 수치는 이번 실행이 아니라 EXP-005의 `phase=before` 실행분을 재사용한 것이다 — 그 사이 LLM 응답 자체의 변동성까지는 통제하지 못했다.
- 단일 실행, 반복 없음. Execution Accuracy가 "동일"하다는 결론도 19문항 중 정확히 같은 수(9개)가 통과했다는 것이지 같은 문항이 통과한 게 아니다(10번↔11번 스왑) — 표본이 작아 이 스왑 자체가 우연일 가능성도 배제 못 한다.
- 이번 실험은 "프롬프트 보강 + 캐시 기반 조립"을 한 번에 같이 바꿔서, 토큰 증가가 정확히 어느 요인(전체 렌더링 후보 설명 vs 근거 서술 요구 vs recall 편향으로 인한 최종 schema_text 크기 증가) 때문인지 분리하지 않았다.
