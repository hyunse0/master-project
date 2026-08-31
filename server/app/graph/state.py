from typing import TypedDict


class GraphState(TypedDict, total=False):
    # ── 입력 ──────────────────────────────────────────────────
    question: str
    domain: str
    run_id: str
    tags: dict          # {"schema_rag_mode": "rag"|"full_dump", "max_retries": int, "experiment": str, ...}
    review_config: dict  # {"schema": bool, "sql": bool} — B는 항상 False/False, C를 위해 필드만 존재

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

    # ── schema_linking_node / schema_review_node 산출 ────────
    schema_candidates: list[str]
    schema_candidate_details: list[dict]  # [{table, comment, score, columns}] — 검토 화면 표시용
    confirmed_schema: list[str]
    schema_text: str

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
