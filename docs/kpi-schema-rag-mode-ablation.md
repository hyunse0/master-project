# KPI 실험: 스키마 RAG 검색 vs 전체 스키마 덤프

## 목적

`data-access-copilot-plan.md`의 Tier1 항목 "토큰 이코노미 대시보드"가 주장하는 "전체 스키마 덤프 대신 Qdrant 검색으로 컨텍스트 축소" 효과를 실측 숫자로 검증한다.

## 실험 설정

- 날짜: 2026-08-24
- 도메인: `poc_prostate`
- 비교축: `schema_linking_node`가 관련 테이블을 Qdrant에서 검색해 스키마 텍스트를 줄이는 방식(`rag`) vs 대상 도메인의 전체 16테이블 스키마를 그대로 프롬프트에 넣는 방식(`full_dump`)
- 벤치마크 질의셋: `server/domains/poc_prostate/benchmark_queries.json`, 정답 라벨 없는 14건 (집계/그룹핑/조인 혼합, 난이도 easy~hard)
- 채팅 모델: `gpt-4.1-mini` (SK AI Talent Lab 게이트웨이)
- 재현 명령어:
  ```
  python eval/token_cost_comparison.py --domain poc_prostate --compare schema_rag_mode=rag,full_dump
  ```
- 원본 데이터: app-db `token_usage`/`run_metrics` 테이블, `tags->>'experiment' = 'schema_rag_mode_ablation'`로 조회 가능

## 결과

| 모드 | 총 토큰 | LLM 호출 수 | 평균 지연시간 | 성공률 |
|---|---|---|---|---|
| **rag** (Qdrant 검색) | **57,187** | 42 | 10,049ms | 92.9% (13/14) |
| **full_dump** (전체 16테이블 덤프) | 104,056 | 43 | 6,008ms | 92.9% (13/14) |

## 분석

- **토큰 사용량 -45%** (104,056 → 57,187): 성공률 저하 없이 스키마 텍스트를 검색된 소수 테이블로 줄인 효과가 실측으로 확인됨. 토큰 이코노미 주장의 근거로 사용 가능.
- **지연시간은 rag가 약 4초 더 느림** (10.0s vs 6.0s 평균): rag 모드는 질문을 임베딩해 Qdrant를 검색하는 API 호출이 추가로 들어가는 반면, full_dump는 이 단계를 생략하기 때문. 토큰/비용 절감과 지연시간 사이의 트레이드오프로 해석.
- **성공률은 두 모드 동일** (92.9%, 13/14) — 스키마를 줄여도 정확도 저하는 관찰되지 않음.
- **공통 실패 1건**: "연령대별로 어떤 수술 종류가 가장 많았는지 알려줘" — 두 모드 모두에서 실패. RAG 여부와 무관한 별도 이슈(랭킹/윈도우 함수가 필요한 고난도 질의로 추정)로, 별도 조사 필요.

## 한계

- 벤치마크 14건은 방향성 확인용 표본으로, 통계적으로 충분히 큰 표본은 아님.
- `expected_sql` 기반 정확도 채점(Execution Accuracy)은 아직 golden set이 없어 포함되지 않음 — 지금의 "성공/실패"는 SQL이 검증·실행까지 통과했는지만 보고, 결과값이 실제로 맞는지는 확인하지 않음.
