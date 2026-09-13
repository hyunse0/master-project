"""비용 대시보드용 조회 API. B단계에서 이미 쌓이고 있는 app-db token_usage/runs 테이블을
읽기만 한다 — 새 테이블/스키마 변경 없음 (docs/cost-dashboard-design.md 참고).
"""
from fastapi import APIRouter, HTTPException

from app.db.app_db import get_app_db_connection
from app.observability import cost_tracker

router = APIRouter(tags=["cost"])

# group_by는 사용자 입력이라 SQL에 직접 꽂지 않고, 허용된 축만 화이트리스트로 매핑한다.
# difficulty는 "어떤 모델로 갈렸는지"가 핵심이라 model을 함께 묶어 그룹핑한다.
_GROUP_BY_CONFIGS = {
    "schema_rag_mode": {"columns": ["tags->>'schema_rag_mode' AS schema_rag_mode"], "group_by": "tags->>'schema_rag_mode'"},
    "difficulty": {"columns": ["tags->>'difficulty' AS difficulty", "model"], "group_by": "tags->>'difficulty', model"},
    "model": {"columns": ["model"], "group_by": "model"},
    # judge(LLM-as-a-judge) 등 평가 전용 노드가 생성 모델과 분리됐는지 비용 대시보드에서
    # 바로 확인하기 위한 축 — eval 스크립트가 남긴 토큰 사용량(node="faithfulness_judge" 등)도
    # runs 테이블 등록 여부와 무관하게 token_usage에서 직접 집계되므로 함께 잡힌다.
    "node": {"columns": ["node", "model"], "group_by": "node, model"},
}


def _aggregate_by_node(calls: list[dict]) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for c in calls:
        key = (c["node"], c["model"])
        bucket = buckets.setdefault(key, {"node": c["node"], "model": c["model"], "calls": 0, "tokens": 0})
        bucket["calls"] += 1
        bucket["tokens"] += c["input_tokens"] + c["output_tokens"]
    return list(buckets.values())


@router.get("/runs/{run_id}/cost")
def get_run_cost(run_id: str) -> dict:
    calls = cost_tracker.get_run_usage(run_id)
    total_input = sum(c["input_tokens"] for c in calls)
    total_output = sum(c["output_tokens"] for c in calls)
    return {
        "run_id": run_id,
        "calls": calls,
        "by_node": _aggregate_by_node(calls),
        "call_count": len(calls),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
    }


@router.get("/cost/recent-runs")
def get_recent_runs(limit: int = 5, domain: str | None = None) -> dict:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.run_id, r.question, r.state_snapshot->>'difficulty' AS difficulty, r.created_at,
                       COALESCE(SUM(tu.input_tokens + tu.output_tokens), 0) AS total_tokens
                FROM runs r
                LEFT JOIN token_usage tu ON tu.run_id = r.run_id
                WHERE (%(domain)s::text IS NULL OR r.domain = %(domain)s)
                GROUP BY r.run_id, r.question, r.state_snapshot, r.created_at
                ORDER BY r.created_at DESC
                LIMIT %(limit)s
                """,
                {"domain": domain, "limit": limit},
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()
    return {"runs": rows}


@router.get("/cost/summary")
def get_cost_summary(
    group_by: str = "schema_rag_mode",
    domain: str | None = None,
    since: str | None = None,
) -> dict:
    config = _GROUP_BY_CONFIGS.get(group_by)
    if config is None:
        raise HTTPException(400, f"지원하지 않는 group_by: {group_by} (허용: {list(_GROUP_BY_CONFIGS)})")

    params = {"domain": domain, "since": since}
    where = """
        WHERE (%(domain)s::text IS NULL OR r.domain = %(domain)s)
          AND (%(since)s::timestamptz IS NULL OR tu.created_at >= %(since)s::timestamptz)
    """

    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COALESCE(SUM(tu.input_tokens), 0)                     AS input_tokens,
                       COALESCE(SUM(tu.output_tokens), 0)                    AS output_tokens,
                       COALESCE(SUM(tu.input_tokens + tu.output_tokens), 0)  AS total_tokens,
                       COUNT(*)                                              AS call_count,
                       COUNT(DISTINCT tu.run_id)                             AS run_count
                FROM token_usage tu
                LEFT JOIN runs r ON r.run_id = tu.run_id
                {where}
                """,
                params,
            )
            overall_cols = [d[0] for d in cur.description]
            overall = dict(zip(overall_cols, cur.fetchone()))

            cur.execute(
                f"""
                SELECT {', '.join(config['columns'])},
                       SUM(tu.input_tokens)                     AS input_tokens,
                       SUM(tu.output_tokens)                    AS output_tokens,
                       SUM(tu.input_tokens + tu.output_tokens)  AS total_tokens,
                       COUNT(*)                                 AS call_count,
                       COUNT(DISTINCT tu.run_id)                AS run_count
                FROM token_usage tu
                LEFT JOIN runs r ON r.run_id = tu.run_id
                {where}
                GROUP BY {config['group_by']}
                ORDER BY total_tokens DESC
                """,
                params,
            )
            cols = [d[0] for d in cur.description]
            groups = [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    overall["avg_tokens_per_run"] = (
        round(overall["total_tokens"] / overall["run_count"], 1) if overall["run_count"] else 0
    )
    for row in groups:
        row["avg_tokens_per_run"] = (
            round(row["total_tokens"] / row["run_count"], 1) if row["run_count"] else 0
        )

    return {"group_by": group_by, "domain": domain, "since": since, "overall": overall, "groups": groups}
