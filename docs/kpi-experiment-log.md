# KPI 실험 로그

에이전트를 "완성"이 아니라 "계속 보완"하는 단계로 넘어가면서, 이후 시도하는 개선(프롬프트 튜닝, 라우팅 로직 변경, 파이프라인 구조 변경, few-shot 전략 변경 등)을 전부 이 문서에 실험 단위로 기록한다. 목적은 과제 제출 시 "이런 다양한 시도를 했고, 이런 효과가 있었다 / 효과가 없어서 되돌렸다"를 근거 있는 숫자로 보여주는 것 — **효과가 없었던 시도도 폐기하지 말고 반드시 기록한다.** 실패한 시도의 기록이야말로 "무작정 찔러본 게 아니라 가설을 세우고 검증했다"는 증거다.

---

## 1. 이 문서에 무엇을 기록하는가

에이전트의 정확도·비용·지연시간·사용성 중 하나라도 바뀔 수 있는 변경은 전부 대상이다. 예:
- 프롬프트/가이던스 문구 수정 (`prompt_builder.py`, `sql_generation/{aggregate,list,cohort}.py`)
- 스키마 링킹·few-shot 검색 로직/스코어링 가중치 변경
- 난이도별 모델 라우팅 기준 변경, 재시도 횟수(`max_retries`) 조정
- 검증 게이트(citation/anchor/validator) 규칙 추가·완화
- 그래프 구조 변경(노드 추가/분기 변경)
- 새 서브에이전트·새 도구 추가

**단순 버그 수정, 오탈자, 리팩터링처럼 동작 결과에 영향이 없는 변경은 기록하지 않는다** — 이 문서는 "품질에 영향을 준 시도"의 기록이지 변경 이력 전체가 아니다(그건 git log가 한다).

---

## 1.5 채택 판단 원칙 — 대리지표(proxy metric) 단독 개선은 채택 근거가 아니다

[EXP-005](./detail/exp-005-schema-review-llm-rerank.md)에서 스키마 매핑 F1이 +25.5pp 개선됐는데도 진짜 지표인
Execution Accuracy는 -5.3pp 하락한 사례가 실제로 있었다("표면 어휘 유사도에 낚인 오선택"). 스키마 매핑
정확도·요약 충실도는 파이프라인 중간 단계를 들여다보는 **진단용 지표**일 뿐, 그 자체가 개선 목표가 아니다 —
사람이 실제로 원하는 건 최종 SQL이 맞는지(Execution Accuracy)이고, 중간 지표는 "틀렸다면 어느 단계에서
틀렸는지" 원인 규명에만 쓴다.

그래서 이후 모든 실험은 다음 기준으로 채택/폐기를 판단한다:
- **Execution Accuracy가 유지되거나 개선됐을 때만** 채택 후보로 본다. 스키마 매핑 F1·요약 충실도가 아무리
  좋아져도 Execution Accuracy가 떨어지면 폐기한다(대리지표 개선은 부가 근거일 뿐, 단독 채택 사유가 될 수 없다).
- Execution Accuracy가 동률(유지)일 때는 토큰/지연시간 비용과 스키마 매핑 F1을 타이브레이커로 참고한다
  ([EXP-006](./detail/exp-006-schema-review-grounded-prompt.md), [EXP-007](./detail/exp-007-column-tiered-schema-context.md)이 이미 이 방식으로 판단됨).
- golden_set.json이 없어 Execution Accuracy를 못 재는 도메인/상황이라면, 그 실험은 "정성적 관찰"로만
  기록하고 실측 채택은 보류한다.

---

## 2. 실험 하나당 기록 템플릿

새 실험을 기록할 때는 아래 템플릿을 채워서 **`docs/detail/<EXP-ID 소문자>-<실험 슬러그>.md` 파일로 저장**하고(예: [exp-001-baseline.md](./detail/exp-001-baseline.md)), 이 문서의 [4. 실험 인덱스](#4-실험-인덱스) 표에는 행을 추가하면서 "상세" 칸에 그 파일 링크만 남긴다 — **길이와 무관하게 매 실험마다 이 방식을 따른다.** 이 문서(`kpi-experiment-log.md`) 본문에는 실험 상세 절을 직접 쓰지 않는다 — 실험이 쌓일수록 이 파일이 무한정 길어지는 걸 막고, 인덱스 표만 봐도 전체 그림이 보이게 하기 위해서다.

```markdown
# [실험 ID] 실험 제목

- **날짜**: YYYY-MM-DD
- **상태**: ✅ 채택 | ❌ 폐기 | ⏸️ 보류 | 📝 정성적 관찰

## 배경 / 가설
왜 이 시도를 했는지, 무엇이 문제라고 판단했는지, 바뀌면 뭐가 좋아질 거라 예상했는지.

## 변경 내용
실제로 무엇을 바꿨는지 — 파일 경로, 핵심 diff 요약. 코드가 아니라 "무슨 결정을 내렸는지" 위주로.

## 측정 방법
- 비교축(A/B): 무엇 vs 무엇
- 사용한 도구: `eval/execution_accuracy.py` 등 (3번 섹션 표 참고)
- 데이터셋: 어떤 질의셋으로 몇 건
- 재현 명령어

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| (정확도/토큰/지연시간/성공률 중 해당하는 것) | | | |

## 분석 및 결정
숫자가 왜 이렇게 나왔는지 해석, 트레이드오프가 있다면 명시. 최종적으로 채택했는지/되돌렸는지와 그 이유.

## 새롭게 배운 것
이 실험을 하면서 예상 밖이었던 점, 다음 실험 설계에 참고할 점, 에이전트/데이터/도구에 대해 새로 알게 된 사실. 결과 숫자와는 별개로 "해보기 전엔 몰랐던 것"만 남긴다 — 예상대로 나온 결과는 여기 쓸 게 없는 게 정상이다.

## 한계
표본 크기, 통제 못 한 변수 등 이 결과를 과신하면 안 되는 이유.
```

이 템플릿 그대로 `docs/detail/<파일명>.md`에 저장한다(H1 제목 + H2 섹션) — `kpi-experiment-log.md`에는 절대 붙여넣지 않는다.

### 필드 설명
- **상태**는 4번 인덱스 표에 그대로 노출되는 값이라 아래 4개 중 하나로 고정해서 쓴다. **측정이 끝나기 전에는 로그에 남기지 않는다** — "일단 반영해두고 나중에 재본다"가 아니라 측정까지 마친 뒤 결론이 선 상태로만 기록한다(그래서 "측정중" 같은 중간 상태는 없다).
  - ✅ 채택 — 효과가 확인돼 코드에 남김 (baseline처럼 "되돌릴 대상이 없는" 실험도, 만든 인프라·데이터를 그대로 유지하기로 했다면 채택으로 기록한다)
  - ❌ 폐기 — 효과가 없거나 역효과라 되돌림 (롤백 커밋/PR 링크를 남겨두면 좋음)
  - ⏸️ 보류 — 시도는 설계했지만 아직 착수 전이거나 데이터/인프라 부족으로 중단
  - 📝 정성적 관찰 — 숫자로 재기 애매한 변경(예: 화면 UX 개선)이라 관찰 근거만 기록
- **측정 방법**은 "무엇과 무엇을 비교했는지"가 핵심 — 반드시 통제 변인 하나만 바꾼 A/B 비교로 설계한다. 두 가지 이상을 동시에 바꾸면 어떤 변경이 효과를 냈는지 구분할 수 없다.
- **결과** 표는 최소 1개 이상의 정량 지표가 있어야 한다("좋아진 것 같다"는 기록 대상이 아니다).
- **새롭게 배운 것**은 선택 항목이 아니다 — 정말 아무 것도 새로 안 배웠으면 "예상대로였음"이라고 한 줄이라도 쓴다. 이 필드가 쌓여야 "무작정 찔러본 게 아니라 가설을 세우고 검증하면서 이해도가 늘었다"는 근거가 된다.

---

## 3. 측정 도구 매핑

| 무엇을 재고 싶을 때 | 도구 | 비고 |
|---|---|---|
| SQL이 실제로 정답을 냈는지 (정확도) | `eval/execution_accuracy.py` | `domains/<domain>/golden_set.json` 필요 — 없으면 이 축은 측정 불가, 검증/실행 성공 여부까지만 대체 지표로 사용. golden_set.json이 있으면 질문당 `graph.invoke()` 1회로 스키마 매핑 정확도·요약 충실도까지 **한 번에 같이 계산**된다(아래 두 항목 참고) — LLM을 3번 태울 필요 없음. "Golden Set 평가" 화면의 골든셋 목록 패널에 있는 "지금 실행" 버튼으로도 실행 가능(백그라운드 job, 진행률 폴링) |
| 스키마 링킹이 정답 테이블을 잘 찾는지 | `eval/execution_accuracy.py`의 실행 결과에 포함 | 별도 실행 불필요 — 위 execution_accuracy 실행 시 자동으로 함께 나온다. `eval/schema_mapping_accuracy.py`는 그 결과 중 스키마 매핑(precision/recall/f1) 부분만 뽑아 보여주는 얇은 CLI 래퍼로 남아있다 |
| 결과 요약 문장이 실제 결과와 일치하는지 | golden_set.json 있으면 `eval/execution_accuracy.py`에 포함, 없으면 `eval/condition_summary_faithfulness.py` | golden_set이 있는 도메인은 execution_accuracy 실행에 자동 포함(같은 그래프 실행에서 LLM judge까지 같이 돎). golden_set이 없는 도메인은 `benchmark_queries.json` 기준으로 이 스크립트를 독립 실행 — 정답 SQL이 없어도 판정 가능(골든셋 불필요 축) |
| 재시도/self-correction이 실제로 고쳐내는지 | `eval/self_correction_ablation.py` | `benchmark_queries.json` 기준(golden_set 불필요), retry on/off, 실패유형별 교정 성공률. "Golden Set 평가" 화면의 "Self-correction 귀인" 패널에 있는 "지금 실행" 버튼으로도 실행 가능(execution_accuracy와 별도 job — graph.stream() 기반이라 같은 루프에 못 합침) |
| 코드 변경 전/후 토큰·비용·지연시간·성공률 비교 | `eval/token_cost_comparison.py --compare <tag_key>=<v1>,<v2>` | 화면(Eval 탭)에는 노출하지 않는 CLI 전용 도구 — `tags`를 런타임에 읽어 분기하는 기존 토글(`schema_rag_mode`, `routing_mode`)은 값 두 개를 한 번에 콤마로 줘서 그 자리에서 A/B. 프롬프트 문구 수정처럼 코드 자체를 바꾸는 개선은 런타임 토글이 안 되므로, `--compare phase=before`로 변경 전 한 번, 코드 바꾼 뒤 `--compare phase=after --experiment <같은 실험 ID>`로 한 번 더 돌리면(`--experiment`를 반드시 같게) 자동으로 하나의 비교표로 합쳐진다. `--report-only`를 붙이면 재실행 없이 지금까지 쌓인 표만 다시 본다. **모든 실험을 로그에 남길 때 이 도구로 최소 토큰 사용량은 재서 결과표에 넣는다** |
| run 하나의 토큰/비용 상세 | `GET /runs/{id}/cost`, "비용 대시보드" 화면 | 개별 run 디버깅용, 집계 실험에는 `token_cost_comparison.py` 사용 |
| 위 스크립트들의 결과를 화면에서 보기 | "Golden Set 평가" 화면(`/eval/*` API) | 골든셋 목록(질문+정답 SQL+마지막 실행 결과, 접기/펼치기), 난이도별 정답률, 스키마 매핑 정확도, 요약 충실도(판정 실패 사례 접기/펼치기), Self-correction 귀인 패널로 구성. `run_metrics.tags->>'experiment'`로 실험을 구분해서 쌓이므로, 새 실험을 만들 땐 `tags["experiment"]`에 고유한 이름을 준다. 이 화면의 정답률/충실도 등 패널은 **해당 실험 태그로 지금까지 쌓인 모든 실행을 누적 집계**하므로, 특정 1회 실행분만 보려면 `docs/detail/*.md`에 옮겨적을 때 시간 범위로 직접 걸러야 한다(예: exp-001-baseline.md) |

새로운 종류의 실험이라 위 도구로 못 재는 지표가 필요하면, 기존 `run_logger.log(..., tags={...})` / `token_usage` 테이블 위에 새 스크립트를 추가하는 방식을 우선 고려한다(계획 문서 D단계 관측성 인프라를 그대로 재사용) — 새 테이블을 먼저 만들지 않는다.

---

## 4. 실험 인덱스

실험이 쌓이면 아래 표만 보고도 전체 그림(무엇을 시도했고, 뭐가 남았고, 뭐가 버려졌는지)이 보이게 유지한다. 새 실험을 추가하면 이 표에 행을 추가하고, 상세 내용은 2번 섹션 규칙대로 `docs/detail/`의 별도 파일에 둔다.

| ID | 실험 | 상태 | 핵심 결과 | 상세 |
|---|---|---|---|---|
| EXP-001 | 100명 합성 데이터 + golden_set 기반 4대 지표 baseline 실측 | ✅ 채택 | 정답률 47.4%(9/19), 스키마매핑 F1 41.3%, 요약충실도 73.3%(11/15), 1차성공 13/14 | [exp-001-baseline.md](./detail/exp-001-baseline.md) |
| EXP-002 | intent의 미사용 `table_hints`를 `schema_linking` 검색 쿼리에 연결 | ❌ 폐기 | 스키마매핑 F1 41.3% → 40.0%(개선 없음, 소폭 하락) | [exp-002-table-hints-query-fusion.md](./detail/exp-002-table-hints-query-fusion.md) |
| EXP-003 | 고정 Top-5 → Top-10 풀 + 최고점수 대비 상대 스코어 컷오프(0.75)로 후보 테이블 수 동적 조정 | ❌ 폐기 | 스키마매핑 precision 28.4%→30.9%(+2.5pp), recall 90.4%→92.1%(+1.7pp)이나 F1 41.3%→39.7%(-1.6pp) | [exp-003-topk-score-cutoff.md](./detail/exp-003-topk-score-cutoff.md) |
| EXP-004 | Top-10 풀 + 원문 질문-스키마 char-bigram 어휘 overlap으로 최종 Top-5 재정렬 | ❌ 폐기 | Execution Accuracy 47.4%→36.8%(-10.6pp), 스키마매핑 F1 41.3%→40.0%(-1.3pp) — EXP-003보다 뚜렷한 역효과 | [exp-004-char-bigram-rerank.md](./detail/exp-004-char-bigram-rerank.md) |
| EXP-005 | `schema_review`에 LLM 기반 closed-set 재선정 추가 + `schema_text` 재구성(confirmed_schema가 SQL 생성 프롬프트에 반영 안 되던 공백도 같이 메움) | ❌ 폐기 | 스키마매핑 F1 41.3%→66.8%(+25.5pp, precision +42.7pp)이나 Execution Accuracy 47.4%→42.1%(-5.3pp) — 대리지표 대폭 개선에도 진짜 지표(정답률)는 하락, 표면 어휘 유사도에 낚인 오선택이 원인 | [exp-005-schema-review-llm-rerank.md](./detail/exp-005-schema-review-llm-rerank.md) |
| EXP-006 | EXP-005 재선정에 컬럼 근거 강제 + recall 편향 프롬프트 보강, `schema_text` 조립을 DB 재조회 없이 캐시(`schema_candidate_details[].text`) 기반으로 전환 | ✅ 채택 | Execution Accuracy 47.4%→47.4%(유지, 손실 없음), 스키마매핑 F1 41.3%→55.2%(+13.9pp) — 단, 토큰 +46.4%·지연시간 약 +25% | [exp-006-schema-review-grounded-prompt.md](./detail/exp-006-schema-review-grounded-prompt.md) |
| EXP-007 | 확정 테이블의 컬럼을 key(PK/FK)/relevant(임베딩 유사도 상위)/other(이름만 압축) 3단으로 티어링해 `schema_text`·테이블 선정 프롬프트 조립 + 사람 검토 UI를 컬럼 단위로 확장 | ✅ 채택 | Execution Accuracy 36.8%→36.8%(유지), 스키마매핑 F1 59.6%→57.2%(-2.4pp) — 토큰 -19.0%, 단 지연시간 +26.1% | [exp-007-column-tiered-schema-context.md](./detail/exp-007-column-tiered-schema-context.md) |
| EXP-008 | 골든셋을 멀티턴 대화로 확장(23대화/28턴) + eval 러너 턴 지원 추가 — 컨텍스트 주입 전 baseline | ✅ 채택 | Execution Accuracy 전체 32.1%(9/28) — 턴1 39.1%(9/23), 턴2 0.0%(0/4), 턴3 0.0%(0/1). 컨텍스트 주입 없이는 후속 질문 정답률이 완전히 0% | [exp-008-multiturn-golden-set-baseline.md](./detail/exp-008-multiturn-golden-set-baseline.md) |
| EXP-009 | intent/sql_generation 프롬프트에 직전 1턴(질문/확정테이블/SQL/요약) 컨텍스트 주입 | ✅ 채택 | Execution Accuracy 전체 32.1%→42.9%(+10.8pp) — 턴1 39.1%→39.1%(동일, 회귀 없음), 턴2 0.0%→75.0%(+75pp), 턴3 0.0%→0.0%(표본 1건, 턴1 자체가 오답이었던 케이스) | [exp-009-multiturn-context-injection.md](./detail/exp-009-multiturn-context-injection.md) |
| EXP-010 | 조인 정합성 정적 검증 게이트 추가(카티션 조인 탐지, DB 조회 불필요) | 📝 정성적 관찰 | 골든셋 28턴 중 발동 0건(정확도 영향 없음) — 로직 자체는 10개 대표 SQL 패턴 단위 테스트로 검증 완료, 실서비스 관측 필요 | [exp-010-join-validity-gate.md](./detail/exp-010-join-validity-gate.md) |
| EXP-011 | 스키마 후보 풀 확장 — top-N 5→8(A) + FK 1-hop 확장(B) + 컬럼 단위 임베딩 히트(C) | ❌ 폐기 | Execution Accuracy 50.0%→39.3%(-10.7pp), 스키마매핑 F1 58.2%→51.9%(-6.3pp), 요약충실도 95.7%→83.3%(-12.4pp) — 후보가 늘수록 schema_review 재선정 품질이 떨어짐. B는 도메인에 FK 제약이 없어 무효 확인 | [exp-011-schema-candidate-expansion.md](./detail/exp-011-schema-candidate-expansion.md) |
| EXP-012 | intent_node에 애매성 판단(needs_clarification) 필드 추가 + intent_clarification 재질의 게이트(review_config.intent, 기본 꺼짐) 신설 | ✅ 채택 | 턴1(통제군) 39.1%→39.1%(회귀 없음). 재질의 기능은 골든셋으로 측정 불가 — 수동 시나리오로 interrupt→답변→재분류→SQL 반영 전체 사이클 검증 완료 | [exp-012-intent-clarification-gate.md](./detail/exp-012-intent-clarification-gate.md) |

<!-- 새 실험은 이 표에 행을 추가하고, docs/detail/<EXP-ID 소문자>-<슬러그>.md 파일을 새로 만들어 2번 섹션 템플릿으로 상세를 적은 뒤 "상세" 칸에 그 링크를 남긴다 — 이 파일 본문에는 상세 절을 직접 쓰지 않는다 -->

