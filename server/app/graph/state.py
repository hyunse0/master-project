from typing import TypedDict


class GraphState(TypedDict, total=False):
    # ── 입력 ──────────────────────────────────────────────────
    question: str
    domain: str
    run_id: str
    tags: dict          # {"schema_rag_mode": "rag"|"full_dump", "max_retries": int, "experiment": str, ...}
    review_config: dict  # {"schema": bool, "sql": bool} — B는 항상 False/False, C를 위해 필드만 존재

    # ── 멀티턴(F단계) 컨텍스트 — API가 매 턴 시작 시 채워서 넘기는 입력 전용 필드.
    # 그래프 노드가 누적하는 채널이 아니다(LangGraph thread는 지금처럼 턴마다 새로 발급되므로
    # 체크포인트 이월에 의존하지 않는다) — app/graph/conversation_context.py 참고.
    conversation_id: str | None
    turn_no: int
    carry_schema: bool   # true면 schema_linking이 새로 검색하지 않고 prior_turns의 확정 스키마를 재사용
    prior_turns: list[dict]
    # [{question, confirmed_schema, confirmed_columns, sql, summary, task_type}] — 직전 1턴.
    # 직전 턴이 success로 끝나지 않았으면 빈 리스트(이을 확정 결과가 없음).

    # ── intent_node 산출 ─────────────────────────────────────
    intent: str
    task_type: str
    metric: str
    dimensions: list[str]
    time_range: dict
    difficulty: str      # easy | medium | hard
    query_type: str      # aggregate | list | cohort — 값 채우는 건 E(9단계)
    intent_status: str        # success | fallback — LLM 분류 성공 여부
    intent_error: str | None  # fallback일 때 원인(예외 메시지)

    # ── intent_clarification_node(F단계) — review_config.intent 게이트 ─────
    # schema_review/sql_review와 같은 성격의 human-in-the-loop: 게이트가 꺼져 있으면(기본)
    # needs_clarification이 True여도 멈추지 않고 그대로 진행한다.
    needs_clarification: bool
    clarification_question: str | None
    clarification_answer: str | None  # intent_clarification이 interrupt 재개 시 채움
    clarification_rounds: int         # 무한 재질의 루프 방지 — 1회 상한

    # ── schema_linking_node / schema_review_node 산출 ────────
    schema_candidates: list[str]
    # [{table, comment, score, columns, text, column_tiers, column_details, foreign_keys}]
    # column_tiers: {key, relevant, other} 컬럼명 목록(key=PK∪FK, relevant=관련도 상위, other=압축).
    # column_details: {컬럼명: {data_type, comment, is_primary_key, is_foreign_key, score}} — 전체 컬럼.
    # text는 이제 column_relevance.render_tiered_schema_block()이 만든 티어링 렌더링.
    # 검토 화면 표시 + schema_review의 schema_text 재조립(_assemble_schema_text) 양쪽에 쓰인다.
    schema_candidate_details: list[dict]
    confirmed_schema: list[str]
    # 사람이 확정한 테이블별 non-key 컬럼의 완전 대체 목록(부분 델타 아님).
    # None이면(자동 경로) 알고리즘의 column_tiers["relevant"]를 그대로 쓴다.
    confirmed_columns: dict[str, list[str]] | None
    schema_text: str
    # schema_linking_node(rag 모드)만 채우는 질문 임베딩 — schema_review_node가 후보 밖
    # 테이블을 즉석 티어링할 때 재계산 없이 재사용한다. API 응답에는 노출하지 않는다.
    question_embedding: list[float] | None

    # ── sql_generation_node 산출 ──────────────────────────────
    few_shot_examples: list[dict]
    sql: str
    sql_prompt: str
    sql_raw: str

    # ── 재시도 제어 (validation_node / execution_node가 채움) ──
    retry_count: int
    retry_feedback: str | None
    retry_error_code: str | None

    # ── execution_node 산출 ───────────────────────────────────
    columns: list[str]
    rows: list[dict]
    row_count: int
    execution_error: str | None
    summary: str
