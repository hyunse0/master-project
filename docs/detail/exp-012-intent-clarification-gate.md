# EXP-012 intent_node 애매성 판단(needs_clarification) 추가 + intent_clarification 재질의 게이트 신설

- **날짜**: 2026-09-08
- **상태**: ✅ 채택

## 배경 / 가설

멀티턴 설계 논의에서 나온 제안 — "직전 턴 컨텍스트로도 해소되지 않는 진짜 모호한 질문"에 대해 `schema_review`/`sql_review`와 같은 성격의 human-in-the-loop 게이트를 하나 더 두면, 무리하게 추측한 SQL 대신 사용자에게 되물어 정확도를 높일 수 있을 것이라는 가설. `review_config.intent`라는 세 번째 게이트로 설계해 기본값은 꺼짐 — 꺼져 있으면 `needs_clarification`이 True로 나와도 멈추지 않고 그대로 진행한다(기존 두 게이트의 off-path와 동일한 철학).

## 변경 내용

- `server/app/graph/state.py`: `needs_clarification`/`clarification_question`/`clarification_answer`/`clarification_rounds` 필드 추가.
- `server/app/graph/nodes/intent.py`: `_INTENT_PROMPT` JSON 스키마에 `needs_clarification`/`clarification_question` 필드 추가(항상 포함 — 게이트 상태와 무관). `clarification_answer`가 있으면(재질의 후 재진입) 질문에 병합해 재분류하고, 병합된 `question`을 상태에 반영해 이후 노드(schema_linking/sql_generation)에도 전파.
- 신규 `server/app/graph/nodes/intent_clarification.py`: `review_config.intent` 게이트 + `needs_clarification` + `clarification_rounds` 상한(1회)을 확인해 `interrupt()`.
- `server/app/graph/build.py`: `intent → intent_clarification → schema_linking`로 배선, `intent_clarification`에서 재개 시 `clarification_answer`가 있으면 `intent`로 되돌아가는 조건부 엣지 추가.
- `server/app/api/run_routes.py`: `_finalize()`가 `next_node == "intent_clarification"`이면 `status="interrupted_intent"` + `clarification_question` 노출, `ResumeRequest.clarification_answer` 추가, `resume_run()` 3-way 분기.
- 부수 수정: `server/app/graph/nodes/execution.py` — 테스트 중 발견한 기존 버그(row 값의 `Decimal`이 `run_manager.save_snapshot()`의 `json.dumps()`를 크래시시킴, 특히 resume 경로에서 요청 자체가 실패)를 DB 결과를 읽는 시점에 `float` 변환으로 수정. 동작 변화가 아니라 버그 수정이라 별도 실험으로 기록하지 않음(1번 섹션 기준).

## 측정 방법

- 비교축(A/B): `review_config.intent` 게이트 자체는 기본 꺼짐이라 골든셋에 영향이 없어야 함 — intent 프롬프트에 상시 추가된 두 필드가 기존 분류 품질에 회귀를 주는지가 실측 대상. 변경 전은 직전 커밋 상태(EXP-009 이후, `carry_schema` 관련 코드는 동시 편집 충돌로 되돌아간 상태 — 자세한 건 세션 기록 참고)에서 다시 잰 수치.
- 사용한 도구: `eval/execution_accuracy.py`(골든셋 회귀 확인) + 수동 스크립트(재질의 기능 자체 검증 — golden_set 문항은 전부 모호하지 않게 설계돼 있어 게이트가 자연 발동하지 않음)
- 데이터셋: `golden_set.json` 23개 대화, 28턴
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  ```

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (전체 28턴) | 11/28 (39.3%) | 13/28 (46.4%) | +7.1pp |
| Execution Accuracy — 턴1 (23개, 게이트 무관 통제군) | 9/23 (39.1%) | 9/23 (39.1%) | 0pp (완전 동일) |
| Execution Accuracy — 턴2 (4개) | 2/4 (50.0%) | 3/4 (75.0%) | +25pp(표본 4건) |
| Execution Accuracy — 턴3 (1개) | 0/1 (0.0%) | 1/1 (100.0%) | 표본 1건 |
| Schema Mapping F1 | 52.7% | 63.7% | +11.0pp |
| Condition Summary Faithfulness | 18/22 (81.8%) | 22/23 (95.7%) | +13.9pp |

## 분석 및 결정

- **턴1(23개, 프롬프트 변경의 영향만 받고 새 기능과는 무관한 통제군)이 정확히 동일한 개수**로 나왔다 — 항상 켜지는 두 필드 추가가 기존 분류·생성 품질에 회귀를 주지 않았다는 근거. 이 결과로 "채택해도 안전하다"고 판단.
- 턴2/3의 상승은 표본이 각 4건·1건으로 극히 작고, 로봇수술 후속질문 시나리오의 스키마 테이블 선택 자체가 실행마다 자연 변동한다는 걸 EXP-009/이전 수동 테스트에서 이미 여러 차례 확인했으므로, 이 실험(프롬프트 필드 추가)이 원인이라고 인과를 주장하지 않는다 — 정상적인 실행 간 변동으로 본다.
- 재질의 기능 자체(interrupt→답변→재분류)는 골든셋으로 측정할 수 없었다(모든 문항이 애초에 모호하지 않게 설계됨). 대신 "위험도가 높은 환자만 보여줘" 같은 실제 모호한 질문으로 수동 검증: `needs_clarification=true` 정상 발동 → `interrupted_intent`로 정지 → 답변("Gleason Grade Group 4 이상을 고위험군으로 간주") 제공 후 resume → intent 재분류 → 그 정의가 최종 SQL의 `WHERE` 조건에 정확히 반영되어 실행까지 성공하는 전체 사이클을 확인했다.
- 통제군 회귀 없음 + 새 기능 정상 동작 + 기본값 꺼짐(기존 사용자 경험 무영향)이므로 채택한다.

## 새롭게 배운 것

- **모델이 모호성 임계값을 꽤 보수적으로 잡는다**: "최근 환자 수를 알려줘"(기준 시점 불명확)조차 스스로 합리적 기본값(최신 방문일 기준)을 가정하고 재질의를 걸지 않았다. 실제로 발동한 건 "위험도가 높은 환자만 보여줘"처럼 지표 정의 자체가 도메인 스키마에 대응점이 전혀 없는 경우뿐이었다 — 프롬프트 지침("최대한 합리적인 기본값을 가정하고 정말 필요할 때만 true")이 의도한 대로 보수적으로 작동한다는 걸 확인했다.
- **재질의 답변은 question 텍스트 갱신만으로 하류 노드에 자연 전파된다**: 별도 파이프라인 분기 없이, intent_node가 병합한 question을 state에 되돌려 쓰는 것만으로 schema_linking·sql_generation이 사용자가 준 정의를 그대로 반영했다 — 설계 예상대로였다.
- **예상 밖의 버그 발견**: resume 저장이 `Decimal` 직렬화 오류로 크래시하는 기존 버그가 있었다. eval 경로에서는 `run_metrics 기록 실패` 로그만 찍고 조용히 넘어가던 문제가, 실제 서비스의 resume 경로에서는 요청 자체를 실패시키는 훨씬 심각한 형태로 나타난다는 걸 이번에 재질의 기능을 수동 검증하다가 우연히 발견했다.

## 한계

- 골든셋에 모호한 질문이 없어 재질의 기능 자체의 정밀도/재현율은 정량 측정하지 못했다 — 다음 단계로 "이 질문은 원래 재질의가 나와야 정상"인 골든셋 항목(예: `expects_clarification: true`)을 추가하는 걸 고려할 만하다.
- 턴2/3 표본이 각각 4건, 1건으로 매우 작아 그 구간 수치는 통계적 의미를 두면 안 된다.
- `carry_schema`(5단계, schema_linking 스키마 재사용)는 다른 세션과의 동시 편집 충돌로 구현이 유실돼 이번 스코프에서 제외됐다 — 재구현 없이 6단계로 건너뛰기로 결정됨.
