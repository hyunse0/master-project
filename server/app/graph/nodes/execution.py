"""SQL 실행 + zero-row 재검 + 응답 요약 합성.

rag-practice SqlGenPipeline._execute()/_compose_response()를 그대로 포팅하되 DSN을
app/db/postgres_client(대상 도메인 접속 정보 기반)로 교체했다.
"""
import logging
import re

import psycopg2
import psycopg2.extras
import sqlglot

from app.db.postgres_client import get_domain_connection
from app.domain.loader import DomainConfig
from app.graph.state import GraphState
from app.llm.base import TokenCountingLLM
from app.llm.router import select_llm
from app.sql.value_anchor import check_value_anchors, extract_code_column_filters

logger = logging.getLogger(__name__)

_MAX_ROWS = 500


def make_execution_node(domain: DomainConfig, llm_router: dict[str, TokenCountingLLM]):
    def execution_node(state: GraphState) -> dict:
        sql = state["sql"]
        retry_count = state.get("retry_count", 0)
        run_id = state["run_id"]
        difficulty = state.get("difficulty")
        tags = {**(state.get("tags") or {}), "difficulty": difficulty}
        llm = select_llm(llm_router, difficulty, tags.get("routing_mode", "on"))

        try:
            columns, rows = _execute(domain, sql, _MAX_ROWS)
        except TimeoutError as e:
            logger.warning("  [execution] 타임아웃: %s", e)
            return {
                "retry_count": retry_count + 1,
                "retry_feedback": f"쿼리 타임아웃: {e}\n원본 SQL:\n{sql}",
                "retry_error_code": "TIMEOUT",
            }
        except Exception as e:
            logger.warning("  [execution] 실행 오류: %s", e)
            return {
                "retry_count": retry_count + 1,
                "retry_feedback": f"SQL 실행 오류: {e}\n원본 SQL:\n{sql}",
                "retry_error_code": "UNSAFE_SQL",
            }

        # zero-row 재검 — 코드/명칭 컬럼 필터가 있을 때만
        if len(rows) == 0:
            suspect_filters = extract_code_column_filters(sql)
            if suspect_filters:
                conn = get_domain_connection(domain.connection)
                try:
                    anchor2 = check_value_anchors(sql, conn)
                finally:
                    conn.close()
                if not anchor2.ok:
                    suspect_desc = "; ".join(
                        f"{f['column']}='{f['value']}'" for f in suspect_filters[:3]
                    )
                    logger.info("  [execution] zero-row + 코드컬럼 필터 재검 실패 — 재시도")
                    return {
                        "retry_count": retry_count + 1,
                        "retry_feedback": f"결과 0건 — 의심 필터: {suspect_desc}\n{anchor2.feedback}",
                        "retry_error_code": "ZERO_ROWS_WITH_VALUE_FILTER",
                    }

        summary = _compose_response(llm, run_id, tags, state["question"], sql, columns, rows)
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "summary": summary,
            "execution_error": None,
            "retry_feedback": None,
            "retry_error_code": None,
        }

    return execution_node


def _cap_limit(sql: str, max_rows: int) -> str:
    """SQL의 LIMIT을 max_rows 이하로 강제한다.

    프롬프트가 LLM에게 항상 자체 LIMIT(기본 100)을 포함하도록 요구하므로, 무조건
    "{sql} LIMIT {max_rows}"를 이어붙이면 LIMIT이 두 번 들어가 문법 오류가 난다
    (예: "... LIMIT 100 LIMIT 500"). 기존 LIMIT이 max_rows 이하면 그대로 두고,
    없거나 더 크면 sqlglot으로 안전하게 교체/추가한다.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return sql  # 파싱 실패 시 원본 그대로 — validator가 이미 앞에서 걸렀어야 함

    limit_node = tree.args.get("limit")
    if limit_node is not None:
        try:
            if int(str(limit_node.expression.this)) <= max_rows:
                return sql
        except Exception:
            pass
    return tree.limit(max_rows).sql(dialect="postgres")


def _execute(domain: DomainConfig, sql: str, max_rows: int) -> tuple[list[str], list[dict]]:
    conn = get_domain_connection(domain.connection)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '30s'")
            try:
                cur.execute(_cap_limit(sql, max_rows))
            except psycopg2.DatabaseError as e:
                pgcode = getattr(e, "pgcode", None)
                if pgcode == "57014":  # query_canceled — statement_timeout 초과
                    raise TimeoutError(f"쿼리 타임아웃 (30s 초과): {e}") from e
                raise
            rows = [dict(r) for r in cur.fetchall()]
            columns = [desc[0] for desc in cur.description] if cur.description else []
    finally:
        conn.close()
    return columns, rows


def _rows_to_text(columns: list[str], rows: list[dict]) -> str:
    if not rows or not columns:
        return ""
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join(
        "| " + " | ".join(str(r.get(c, "")) for c in columns) + " |"
        for r in rows
    )
    return f"{header}\n{sep}\n{body}"


def _compose_response(
    llm: TokenCountingLLM,
    run_id: str,
    tags: dict,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[dict],
) -> str:
    """질문 + SQL + 결과로 ## 요약 / ## SQL / ## 결과 3블록 마크다운을 생성한다.

    ## 요약은 LLM이 작성하고, ## SQL · ## 결과는 코드에서 직접 조립한다.
    """
    total = len(rows)

    if total == 0:
        zero_msg = (
            "조건에 맞는 데이터가 없습니다.\n"
            "가능한 원인: ① 필터 조건이 너무 좁음 ② 해당 기간·조건의 데이터 부재"
        )
        return "\n\n".join([f"## 요약\n{zero_msg}", f"## SQL\n```sql\n{sql}\n```"])

    display_n = min(20, total)
    sample = rows[:display_n]
    sample_text = _rows_to_text(columns, sample)
    preview_text = _rows_to_text(columns, rows[:5])

    summary_prompt = (
        "당신은 NL2SQL 응답 작가입니다. ## 요약 섹션만 한국어로 작성하세요.\n"
        "규칙: 2~3문장, 핵심 수치 강조, 결과에 없는 숫자 인용 금지,\n"
        "SQL 수정·재작성·재실행 시도 금지.\n\n"
        f"질문: {question}\n"
        f"전체 결과: {total}건 (상위 {display_n}건 표시)\n"
        f"컬럼: {', '.join(columns)}\n"
        f"미리보기(상위 5건):\n{preview_text}\n\n"
        "## 요약\n"
    )
    try:
        raw_summary = llm.generate(
            summary_prompt, run_id=run_id, node="execution_summary", tags=tags,
        ).strip()
        summary_text = re.sub(r"^##\s*요약\s*\n?", "", raw_summary, flags=re.IGNORECASE).strip()
    except Exception as e:
        logger.warning("응답 합성 실패: %s", e)
        summary_text = f"총 {total}건이 조회됐습니다."

    count_note = (
        f"\n\n*(전체 {total}건 중 상위 {display_n}건 표시)*" if total > display_n else ""
    )

    parts = [
        f"## 요약\n{summary_text}",
        f"## SQL\n```sql\n{sql}\n```",
        f"## 결과 (상위 {display_n}건)\n{sample_text}{count_note}",
    ]
    return "\n\n".join(parts)
