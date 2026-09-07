# EXP-007 스키마 컨텍스트 컬럼 티어링 — key/relevant/other 3단 압축 + 사람 검토 컬럼 단위 확장

- **날짜**: 2026-09-05
- **상태**: ✅ 채택

## 배경 / 가설

지금까지 스키마 링킹/검토는 테이블 단위로만 동작했다 — `schema_linking_node`가 후보 테이블을 고르고 `schema_review_node`가 그중 확정 테이블을 좁혀도, 확정된 테이블의 **전체 컬럼**(타입/코멘트/PK/FK 포함)이 그대로 `schema_text`에 다시 덤프됐다. 컬럼이 수십~백 개에 달하는 테이블(`poc_prostate_patient_info`는 약 90개)에서는 이 전량 덤프가 SQL 생성 LLM과 사람 검토자 모두에게 "이 중 어떤 컬럼이 실제로 필요한가"를 판단하기 어렵게 만드는 것으로 보였다.

해결 방향으로 컬럼을 무조건 잘라내는 pruning이 아니라 3단 압축(compression)을 도입했다: **key**(PK + 이 테이블의 FK 컬럼, 항상 상세) / **relevant**(질문 임베딩과의 코사인 유사도 상위 컬럼, 상세) / **other**(나머지, 이름만 압축 — 존재는 알리되 타입/코멘트는 생략). 이 방식이면 토큰을 줄이면서도 필요한 컬럼이 완전히 사라지는 일은 없을 것이라 예상했다.

이 실험은 EXP-006이 "새롭게 배운 것"에 명시적으로 남긴 미시도 대안 — "후보 설명은 압축 포맷 유지하되 recall 편향 지침만 남기는 조합" — 을 구조적으로 실현한 것이기도 하다. EXP-006은 후보 설명을 전체 렌더링(비압축)으로 늘려 토큰이 +46.4% 증가했는데, 이번엔 반대로 후보 설명 자체를 컬럼 티어링으로 압축해 토큰을 줄이면서 recall 편향 지침(EXP-006에서 이미 도입, 유지)은 그대로 둔 조합을 시도했다.

## 변경 내용

- `server/app/sql/column_relevance.py`(신규): 컬럼 티어 분류(`classify_columns_for_tables` — 질문 임베딩과 컬럼명+코멘트 임베딩의 코사인 유사도, `EmbeddingEngine.embed_batch()`로 후보 테이블 전체 컬럼을 한 번에 배치 처리) + 티어링 반영 렌더러(`render_tiered_schema_block` — key/relevant는 상세 라인, other는 이름만 압축한 한 줄, "타입/설명 없음" 경고 문구를 텍스트 자체에 포함).
- `server/app/graph/nodes/schema_linking.py`: top-5 후보 테이블 각각에 대해 `schema_provider.get_table_info()`로 introspect한 뒤 위 모듈로 컬럼 티어링을 계산해 `schema_candidate_details[i]`에 `column_tiers`/`column_details`/`foreign_keys`를 추가하고, `text`를 티어링된 렌더링으로 교체. 이미 계산된 질문 임베딩을 재사용(재계산 없음)하고, 개별 테이블 introspection 실패는 try/except로 감싸 해당 테이블만 "이름만" 폴백.
- `server/app/graph/nodes/schema_review.py`: `_format_candidates()`(테이블 선정 프롬프트용 후보 설명)가 이제 자동으로 압축된 티어링 텍스트를 쓰게 됨(구조 변경 없이 입력 데이터만 바뀜). `_assemble_from_cache()`를 `_assemble_schema_text()`로 교체해 확정 테이블들의 `schema_text`를 컬럼 티어링 반영해 재조립하고, 사람의 `confirmed_columns`(테이블별 non-key 컬럼의 완전 대체 목록) 오버라이드가 있으면 relevant 티어 대신 사용(key 티어는 오버라이드 여부와 무관하게 항상 강제 포함). 후보 캐시에 없는 테이블(사람이 후보 밖 테이블 직접 추가)은 그 테이블만 즉석 introspect+티어링, 그마저 안 되면 완전 비압축 폴백.
- `server/app/graph/state.py`: `question_embedding`(신규, API 미노출), `confirmed_columns`(신규) 필드 추가, `schema_candidate_details` shape 주석 갱신.
- `server/app/api/run_routes.py`: `ResumeRequest.confirmed_columns` 추가, interrupt 재개 값을 `list[str]`에서 `{"tables": [...], "columns": {...}}`로 확장(진행 중이던 체크포인트를 위해 옛 `list[str]` shape도 방어적으로 계속 처리).
- 프론트엔드(`SchemaReviewCard.tsx` 등): 테이블 체크 시 컬럼 패널이 펼쳐져 key(잠금+배지)/relevant(기본 체크)/other(접힘, 기본 미체크) 컬럼을 사람이 직접 조정 가능하도록 확장. `useRunReview.ts`가 `columnChecked` 상태를 관리하고 승인 시 `confirmed_columns`를 함께 전송.

## 측정 방법

- 비교축(A/B): 컬럼 티어링 도입 전(baseline, 현재 main — EXP-006까지 반영 + 이후 커밋 4건) vs 도입 후(이번 변경)
- 사용한 도구:
  - `eval/execution_accuracy.py` — golden_set 19문항 (Execution Accuracy + Schema Mapping Accuracy + 요약 충실도를 한 번에 계산)
  - `eval/token_cost_comparison.py --compare phase=before/after --experiment EXP-007` — benchmark_queries.json 14문항, `review_config` 둘 다 꺼진 자동 경로만 실행(코드 변경이라 런타임 토글 불가, `git stash`로 변경 전/후 코드를 오가며 같은 벤치마크셋을 두 번 실행)
- 재현 명령어:
  ```
  git stash -u                       # 컬럼 티어링 변경분 제외(baseline)
  python eval/execution_accuracy.py --domain poc_prostate
  python eval/token_cost_comparison.py --domain poc_prostate --compare phase=before --experiment EXP-007
  git stash pop                      # 변경분 복원
  python eval/execution_accuracy.py --domain poc_prostate
  python eval/token_cost_comparison.py --domain poc_prostate --compare phase=after --experiment EXP-007
  ```

## 결과

| 지표 | 변경 전 (baseline) | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (golden_set 19문항) | 7/19 (36.8%) | 7/19 (36.8%) | 없음 (단, #3↔#7 문항 스왑) |
| Schema Mapping Precision | 53.5% | 52.2% | -1.3pp |
| Schema Mapping Recall | 76.3% | 71.1% | -5.2pp |
| Schema Mapping F1 | 59.6% | 57.2% | -2.4pp |
| 요약 충실도 | 10/12 (83.3%) | 13/15 (86.7%) | 표본(분모) 자체가 달라 직접 비교 부적절 |
| 토큰 사용량 (benchmark 14문항) | 78,387 tok / 55 LLM 호출 | 63,461 tok / 55 LLM 호출 | -14,926 tok (-19.0%), 호출 수 동일 |
| 평균 지연시간 (benchmark 14문항) | 9,372ms | 11,817ms | +2,445ms (+26.1%) |
| 성공률 (benchmark 14문항, validation/execution 성공 기준) | 92.9% (13/14) | 92.9% (13/14) | 없음 |

## 분석 및 결정

가장 중요한 실질 지표인 Execution Accuracy는 7/19로 완전히 동일했다(다만 EXP-006 때처럼 통과 문항 구성 자체는 바뀜 — "암종 소분류별 환자 분포"가 새로 통과, "집도과별 수술 건수"가 대신 실패). 토큰은 -19.0%로 뚜렷이 줄었는데, 이는 `schema_review`의 테이블 선정 프롬프트(`_format_candidates`)와 최종 `schema_text` 조립 양쪽 모두에서 컬럼 압축이 동시에 효과를 낸 결과다 — EXP-006이 후보 설명을 전체 렌더링으로 늘려 토큰이 +46.4%였던 것과 정반대 방향.

다만 두 가지 비용이 있었다. 첫째, 지연시간이 +26.1% 늘었다 — `schema_linking_node`가 매 실행마다 후보 5개 테이블을 전부 introspect(테이블당 3쿼리)하고 컬럼 임베딩 배치 호출을 추가로 하게 됐기 때문이다. 이는 EXP-006이 "DB 재조회 없이 캐시 기반으로 조립"해 없앴던 비용을 스키마 검토 단계 대신 스키마 링킹 단계에서 다시 지불하는 셈이다. 둘째, Schema Mapping F1이 59.6%→57.2%(-2.4pp, recall 위주로 -5.2pp)로 소폭 하락했다 — 테이블 선정 프롬프트에 들어가는 후보 설명이 압축되면서, LLM이 판단할 수 있는 컬럼 정보가 줄어 애매한 테이블을 포함시키는 recall 편향 지침의 효과가 약해진 것으로 보인다.

Execution Accuracy(진짜 지표)가 정확히 유지되면서 토큰이 19% 줄었고, Schema Mapping F1 하락폭(-2.4pp)은 EXP-006이 확보한 개선폭(+13.9pp)에 비해 작아 감내 가능한 수준으로 판단했다. 또한 이 변경은 KPI 수치 개선 자체보다 "컬럼이 많은 테이블에서 어떤 컬럼이 필요한지 사람이 직접 검토할 수 있게 한다"는 사용성 목표(사람 검토 UI에 컬럼 단위 체크박스 추가)가 주된 목적이었고, 이 부분은 수치화되지 않지만 실제로 동작을 확인했다(아래 참고). 지연시간 증가는 실측된 트레이드오프로 남겨두고 채택했다.

## 새롭게 배운 것

- **테이블 선정과 최종 조립, 두 소비처를 하나의 압축 렌더러로 묶었더니 토큰은 크게 줄었지만 두 효과가 뒤섞였다** — Schema Mapping F1 하락이 "선정 프롬프트가 압축돼 판단력이 떨어진 것"인지 "최종 schema_text 압축 자체와는 무관한지"를 분리하지 않았다. EXP-006의 한계("프롬프트 보강 + 캐시 기반 조립을 동시에 바꿔 요인 분리 안 됨")를 이번에도 완전히는 피하지 못했다 — 다음에 F1을 더 끌어올리고 싶다면 "선정 프롬프트만 원래 방식대로 두고 최종 조립만 압축"하는 조합을 분리해서 시도해볼 만하다.
- **DB 재조회 비용을 줄이는 최적화(EXP-006)와 컬럼 단위 정보를 늘리는 최적화(이번 실험)는 서로 반대 방향으로 당긴다** — EXP-006은 schema_review에서 DB 재조회를 없앴는데, 이번 실험은 그 최적화 지점이 아니라 schema_linking 쪽에 새로운 DB 조회(테이블당 3쿼리 × 5테이블)를 추가해 지연시간을 다시 늘렸다. "토큰을 줄이는 변경"이 자동으로 "빨라지는 변경"은 아니라는 걸 재확인했다.
- 실행 중 `eval/execution_accuracy.py`의 요약 충실도 로깅 코드(`run_logger.log`에 `rows`를 그대로 태그로 넘기는 부분)에서 `numeric` 타입 컬럼 값이 포함된 경우 `Decimal` 직렬화 실패 경고가 발생하는 걸 발견했다 — 이번 변경과 무관한 기존 코드의 잠재 버그(수치형 컬럼이 결과에 포함된 질문에서만 발생, 정확도 지표 계산 자체엔 영향 없음)로, 범위 밖이라 이번 실험에서는 고치지 않고 기록만 남긴다.

## 한계

- `execution_accuracy.py`(golden_set 19문항)와 `token_cost_comparison.py`(benchmark_queries 14문항)는 서로 다른 질의셋 — 두 지표를 같은 실행 배치의 결과로 보면 안 된다.
- `git stash`로 변경 전/후를 오간 것 외에는 완전히 통제된 환경이 아니다 — LLM 응답 자체의 변동성, 그 사이 외부 API(게이트웨이) 지연 변동까지는 통제하지 못했다. 지연시간 차이(+26.1%)는 방향성은 신뢰할 만하지만 정확한 폭은 반복 측정 없이는 과신하면 안 된다.
- 이번 실험은 (1) 테이블 선정 프롬프트 압축과 (2) 최종 schema_text 컬럼 티어링을 한 번에 같이 바꿔서, Schema Mapping F1 하락이 정확히 어느 요인 때문인지 분리하지 않았다(위 "새롭게 배운 것" 참고).
- 사람 검토 UI(컬럼 체크박스)의 실제 사용성 효과는 정량 지표로 재지 않았다 — 수동으로 브라우저에서 동작만 확인했다(체크 시 패널 펼침, key 잠금, other 펼치기, 승인 후 override가 `schema_text`에 반영되는 것까지).
- `_TOP_N_RELEVANT_COLUMNS`(8)와 `_RELEVANCE_FLOOR_SCORE`(0.15)는 원칙적 근거 없이 고정한 초기값이다 — 이번 실험은 이 값들을 튜닝하지 않았고, 튜닝은 통제 변인 원칙에 따라 별도 실험으로 분리해야 한다.
