import logging
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

_FORBIDDEN_STMT_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop,
    exp.Create, exp.Alter, exp.TruncateTable,
)


@dataclass
class ValidationResult:
    ok:     bool
    errors: list[str] = field(default_factory=list)


class SqlValidator:
    """LLM이 생성한 SQL의 안전성과 스키마 일치를 검증한다."""

    def __init__(self, allowed_tables: list[str]):
        """allowed_tables: 대상 도메인 스키마의 허용 테이블명 목록 (스키마 접두사 없이)."""
        self._allowed = set(allowed_tables)

    def validate(self, sql: str) -> ValidationResult:
        errors: list[str] = []

        try:
            parsed = sqlglot.parse_one(sql, dialect="postgres")
        except Exception as e:
            return ValidationResult(ok=False, errors=[f"SQL 파싱 실패: {e}"])

        # 1. SELECT 전용 검사
        if isinstance(parsed, _FORBIDDEN_STMT_TYPES):
            errors.append("이 서비스는 읽기 전용입니다.")
        elif not isinstance(parsed, exp.Select):
            errors.append("이 서비스는 읽기 전용입니다.")

        # 2. 참조 테이블 검사
        for table in parsed.find_all(exp.Table):
            tbl_name = table.name.lower()
            if tbl_name not in self._allowed:
                errors.append(f"허용되지 않는 테이블입니다: {tbl_name}")

        return ValidationResult(ok=len(errors) == 0, errors=errors)
