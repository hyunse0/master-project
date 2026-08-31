# EXP-001 100명 합성 데이터 + golden_set 기반 4대 지표 baseline 실측

- **날짜**: 2026-08-30
- **상태**: ✅ 채택

## 배경 / 가설

이 프로젝트는 그동안 정답 SQL(`golden_set.json`)이 없어 Execution Accuracy·Schema Mapping Accuracy 축을 아예 측정할 수 없었고(도구 매핑 표에 명시된 제약), 환자 데이터도 8명뿐이라 연령대별 분포 같은 집계성 질문 상당수가 결과 자체가 무의미했다. 이번 세션에서 (1) 환자 100명 합성 데이터셋 시딩, (2) `golden_set.json` 19문항(기존 벤치마크 14문항 + 3테이블 조인/서브쿼리형 hard 5문항) 작성, (3) `execution_accuracy.run()`이 질문당 `graph.invoke()` 1회로 Execution Accuracy·Schema Mapping Accuracy·Condition Summary Faithfulness 세 지표를 동시에 산출하도록 통합, (4) `self_correction_ablation.py`도 동일 패턴으로 버튼화를 마쳤다. 즉 지금이 "정답 기준 실측이 처음으로 가능해진" 시점이라, 이후 모든 개선 실험이 비교할 기준선(baseline)을 먼저 기록해둔다.

## 변경 내용

- `server/scripts/seed_poc_prostate.py`: 환자 8명 → 100명 합성 데이터셋(멱등 재시딩 스크립트)
- `server/domains/poc_prostate/golden_set.json`: 신규 작성 — 19문항(질문 + 정답 SQL)
- `server/eval/execution_accuracy.py`: `run()`이 질문당 `graph.invoke()` 1회로 execution accuracy + schema mapping accuracy + summary faithfulness(LLM judge)를 동시에 계산·기록하도록 통합(이전엔 스크립트 3개가 같은 골든셋을 각자 처음부터 다시 실행해 LLM을 3배 호출)
- `server/eval/self_correction_ablation.py`: 평가 로직을 `run()`으로 분리, `POST /eval/self-correction/run` 백그라운드 job으로 버튼화
- `server/app/api/eval_routes.py`: `/eval/execution-accuracy/run`, `/eval/self-correction/run`(+ `run-status`), `/eval/golden-set` API 추가
- `client/.../components/eval/EvalTab.tsx`: 골든셋 목록/실행 버튼/결과 펼치기 UI 추가

## 측정 방법

- 비교축: 없음(A/B가 아니라 baseline 최초 측정) — "정답 기준 측정 자체가 불가능했던 상태" → "실측치 확보"
- 사용한 도구: `eval/execution_accuracy.py`(3축 동시 산출), `eval/self_correction_ablation.py`
- 데이터셋: `golden_set.json` 19문항(execution/schema mapping/faithfulness), `benchmark_queries.json` 14문항(self-correction)
- 재현 명령어:
  ```
  python eval/execution_accuracy.py --domain poc_prostate
  python eval/self_correction_ablation.py --domain poc_prostate
  ```
  (또는 "Golden Set 평가" 화면의 "지금 실행" 버튼)

## 결과

| 지표 | 변경 전 | 변경 후 | 차이 |
|---|---|---|---|
| Execution Accuracy (19문항) | 측정 불가 (golden_set 없음) | 9/19 (47.4%) | 최초 확보 |
| Schema Mapping Precision / Recall / F1 | 측정 불가 | 28.4% / 90.4% / 41.3% | 최초 확보 |
| Condition Summary Faithfulness | 4건뿐, 전부 8명 데이터 시절 기록 | 11/15 (73.3%, 현재 데이터 기준) | 최초 확보 |
| Self-Correction 귀인 (14문항) | 3건뿐, 전부 8명 데이터 시절 기록 | 1차 성공 13 / 재시도로 성공 0 / 끝내 실패 1 | 최초 확보 |
| 토큰 사용량 — execution+schema 통합 실행 (19문항) | – | 123,169 tok (input 91,471 / output 31,698) | – |
| 토큰 사용량 — faithfulness judge (15건 판정) | – | 65,164 tok | – |
| 토큰 사용량 — self-correction (14문항, graph.stream) | – | 56,380 tok | – |

## 분석 및 결정

- Recall 90%인데 Precision 28%: schema_linking이 정답 테이블을 놓치는 경우는 거의 없지만 필요 이상으로 많은 테이블을 후보로 끌고 온다 — 다음 개선 후보로 유력.
- Execution Accuracy 47.4%는 hard 5문항(3테이블 조인·서브쿼리·코호트 정의)이 전부 실패한 영향이 크다 — 난이도별 분해가 필요하다(EvalTab의 난이도별 정답률 패널 참고).
- 이번 14문항 중 재시도가 실제로 뭔가를 고친 사례(`corrected_by_retry`)가 0건이었다 — 재시도 로직 효과를 이 표본에서는 아직 관찰하지 못했다. 표본이 작아서인지, 1차 성공률이 높아 재시도가 거의 발동하지 않아서인지는 추가 확인 필요.
- 이 실험은 "되돌릴 변경"이 있는 게 아니라 golden_set.json·100명 데이터·통합 실행 인프라 자체를 만든 것이고, 그 결과물을 그대로 유지하기로 했으므로 상태는 채택으로 기록한다. 실측치 자체는 이후 실험의 "변경 전" 칸에 그대로 재사용한다.

## 새롭게 배운 것

- **정확도보다 스키마 링킹이 먼저 병목이다**: Recall 90%·Precision 28%라는 건 "필요한 테이블을 못 찾는" 문제가 아니라 "필요 이상으로 많은 테이블을 끌고 오는" 문제다. 이건 실측 전엔 몰랐던 것 — 막연히 "SQL 생성이 틀렸겠거니" 짐작했는데, 중간 단계(스키마 링킹) 자체가 이미 노이즈를 만들고 있었다.
- **hard 난이도(3테이블 조인·서브쿼리·코호트)는 지금 전멸 수준이다**: golden_set에 넣은 hard 5문항이 전부 실패했다 — 난이도가 올라갈수록 서서히 나빠지는 게 아니라 특정 복잡도 구간에서 뚝 끊긴다는 걸 처음 확인했다.
- **재시도(self-correction)가 이번 배치에서 아무것도 못 고쳤다**: 재시도 로직이 켜져 있다는 것과 "재시도가 실제로 도움이 된다"는 건 별개라는 걸 숫자로 처음 봤다 — 지금까진 로직이 있으니 당연히 효과가 있을 거라 가정했었다.
- **평가 스크립트 3개가 같은 그래프를 3번씩 다시 태우고 있었다**: execution_accuracy·schema_mapping_accuracy·condition_summary_faithfulness가 각자 독립적으로 골든셋 전체를 처음부터 재실행하고 있어서, 하나의 골든셋을 "제대로" 평가하려면 LLM을 3배 호출해야 했다 — 정확도 축을 늘릴 때마다 비용이 배로 느는 구조였다는 걸 뒤늦게 발견하고 통합했다.
- **eval/CLI로 만든 run은 "실행 히스토리" 화면에 절대 안 잡힌다**: `run_manager.create()`를 호출하는 건 실제 UI(`POST /runs`) 경로뿐이라, 골든셋 평가 화면에 있던 "실행 히스토리에서 보기" 링크가 처음부터 100% 깨진 링크였다(66건 중 0건 매칭 확인) — 화면을 만들 때 이 구분을 놓치면 똑같은 버그가 재발하기 쉽다.

## 한계

- `golden_set.json` 19문항, `benchmark_queries.json` 14문항 모두 표본이 작아 통계적 유의성은 없다.
- 100명 합성 데이터는 실제 임상 분포를 흉내낸 것이라, 여기 나온 절대 수치(47.4% 등)는 "이 코드가 이만큼 좋다"가 아니라 "지금 이 데이터·코드 조합에서 이 정도"로 해석해야 한다.
- 위 Faithfulness/Self-Correction 수치는 이번 실행분만 따로 걸러낸 것이다 — EvalTab 화면 자체는 `run_metrics`에 남아있는 예전(8명 데이터) 기록까지 누적 집계해서 보여주므로 화면 수치와 다를 수 있다.
