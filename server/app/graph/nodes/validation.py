"""SchemaCitation → ValueAnchor → SqlValidator(안전성) 순서로 검증한다.

citation/anchor 실패는 재시도 대상(sql_generation_node로 복귀), SqlValidator(안전성) 실패는
원본 SqlGenPipeline과 동일하게 재시도 없이 종료 대상이다 — 구조적 위반은 프롬프트를
고쳐도 해결되지 않는다고 본 원본 설계를 그대로 따른다.
"""
import logging

from app.db.postgres_client import get_domain_connection
from app.domain.loader import DomainConfig
from app.graph.state import GraphState
from app.sql.schema_citation_validator import validate_schema_citations
from app.sql.validator import SqlValidator
from app.sql.value_anchor import check_value_anchors

logger = logging.getLogger(__name__)


def make_validation_node(domain: DomainConfig, sql_validator: SqlValidator):
    def validation_node(state: GraphState) -> dict:
        sql = state["sql"]
        retry_count = state.get("retry_count", 0)

        conn = get_domain_connection(domain.connection)
        try:
            citation = validate_schema_citations(sql, conn)
            if not citation.ok:
                logger.warning("  [validation] citation 실패: %s", citation.missing)
                return {
                    "retry_count": retry_count + 1,
                    "retry_feedback": citation.feedback,
                    "retry_error_code": "SCHEMA_CITATION_FAIL",
                }

            logger.info("  [validation] 스키마 인용 검증 통과")

            anchor = check_value_anchors(sql, conn)
            if not anchor.ok:
                logger.warning("  [validation] value anchor 실패")
                return {
                    "retry_count": retry_count + 1,
                    "retry_feedback": anchor.feedback,
                    "retry_error_code": "VALUE_ANCHOR_FAIL",
                }
            logger.info("  [validation] 값 존재 검증 통과")
        finally:
            conn.close()

        validation = sql_validator.validate(sql)
        if not validation.ok:
            err = " | ".join(validation.errors)
            logger.warning("  [validation] SQL 검증 실패: %s", err)
            return {
                "execution_error": f"SQL 검증 실패: {err}",
                "retry_feedback": f"SQL 검증 실패: {err}",
                "retry_error_code": "SQL_VALIDATION_FAIL",
            }
        logger.info("  [validation] 안전성 검증 통과")

        return {"retry_feedback": None, "retry_error_code": None}

    return validation_node
