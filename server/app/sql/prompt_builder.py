"""SQL 생성 프롬프트 빌더.

rag-practice/server/sqlgen/prompt_builder.py의 공통 골격(3블록 출력 형식, 절대 규칙,
VALUE_UNCONFIRMED 탈출구, 재시도 가이드)은 그대로 유지하되, 전립선암 전용 하드코딩
(특정 테이블명이 박힌 JOIN 체크리스트, "환각 방지" 컬럼 목록 등)은 빼고
domains/<domain>/prompt_fragments.yaml에서 읽은 텍스트를 [도메인 참고사항] 섹션으로 주입한다.
파일이 없으면 그 섹션을 생략하고 공통 템플릿만으로 동작 — 신규 도메인 연결 시 즉시 동작을 보장한다.
"""
import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
당신은 PostgreSQL SELECT 쿼리 작성 전문가입니다.
메인이 넘긴 질문과 [스키마] 정보만 보고 단일 SELECT 문을 작성하세요.

# 출력 형식 (3블록 필수 — 반드시 이 순서로)

## 의도
<한 줄: 어느 테이블을 어떻게 조인하고 어떤 조건을 거는지>

## SchemaCitation
- schema.table.col : "컬럼 설명" (확인됨)
...
※ 이 블록에 인용한 모든 컬럼은 [스키마] 테이블 정의에서 그대로 찾을 수 있어야 합니다.
   찾을 수 없으면 그 컬럼은 SQL에서 사용 금지.

## SQL
```sql
SELECT ...
```

# 절대 규칙
1. 이 서비스는 읽기 전용입니다. 단일 SELECT 문만. CTE(WITH) 허용.
   DDL/DML/멀티문/INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE 금지.
2. 테이블은 반드시 스키마 명시 (예: poc.table_name).
3. [스키마]에 없는 컬럼·테이블 사용 금지.
4. ORDER BY + LIMIT(기본 100) 항상 포함.
5. PostgreSQL 문법만. SYSDATE/NVL/ROWNUM/DATE_FORMAT/QUALIFY 금지.
   QUALIFY는 CTE + ROW_NUMBER()로 치환.
6. 한글 LIKE는 ILIKE.
7. 컬럼명이 의미를 보장한다고 절대 가정하지 마세요. [스키마]의 코멘트와
   [값 위치] 정보만 근거로 삼으세요.

# [필수] 값-컬럼 검증 (Value Anchoring)
WHERE절에 리터럴 값을 쓸 때 — 아래 조건을 모두 충족해야 합니다:

① [값 위치] 섹션에 해당 값이 found=true로 등재돼 있어야 합니다.
② [값 위치]가 없거나 found=false이면 SQL을 쓰지 말고 반드시 아래 형식으로만 응답:

## VALUE_UNCONFIRMED
- 값: "<리터럴>"
- 후보 컬럼: [<schema.table.col>, ...]
- 요청: value_anchors 재탐색 필요

③ locations가 여러 개면 하나를 골라 SchemaCitation에 선택 근거 명시.
④ 컬럼명이 의미를 보장한다고 절대 가정 금지.
"""

# 에러 코드별 재시도 지침
_RETRY_GUIDE: dict[str, str] = {
    "JOIN_INVALID": (
        "일부 테이블이 다른 테이블과 JOIN 조건 없이 나열되어 카티션 곱 위험이 있습니다.\n"
        "모든 테이블을 JOIN ... ON 조건이나 WHERE 등가조건으로 다른 테이블과 명시적으로 연결하세요.\n"
        "의도적인 전체 조합이 아니라면 조건 없는 콤마 조인이나 CROSS JOIN을 쓰지 마세요."
    ),
    "UNSAFE_SQL": (
        "단일 SELECT/허용 함수만 사용했는지 점검 후 재작성하세요.\n"
        "PostgreSQL 미지원 문법(QUALIFY/ROWNUM/SYSDATE/NVL/DATE_FORMAT)이 있으면 제거하세요.\n"
        "QUALIFY는 CTE + ROW_NUMBER()로 치환하세요."
    ),
    "TIMEOUT": (
        "WHERE 조건을 좁히고, LIMIT를 줄이고, 불필요한 JOIN을 제거하세요."
    ),
    "ZERO_ROWS_WITH_VALUE_FILTER": (
        "결과 0건 + 값 필터가 원인일 가능성이 큽니다.\n"
        "같은 SQL을 다시 쓰지 말고 VALUE_UNCONFIRMED로 반려하여\n"
        "value_anchors 재탐색을 요청하세요."
    ),
}


def _load_yaml(prompt_fragments_path: Path) -> dict:
    if not prompt_fragments_path.is_file():
        return {}
    try:
        return yaml.safe_load(prompt_fragments_path.read_text()) or {}
    except Exception as e:
        logger.warning("prompt_fragments.yaml 로드 실패 (%s): %s", prompt_fragments_path, e)
        return {}


def load_general_notes(prompt_fragments_path: Path, domain_name: str | None = None) -> str:
    """도메인 전체에 적용되는 일반 참고사항(특정 테이블에 종속되지 않는 규칙)을 읽는다.

    소스 두 곳을 합친다 — ① `prompt_fragments.yaml`의 `notes:`(개발 시점에 파일로 미리
    시딩해두는 기본값), ② app-db `domain_notes`(table_name IS NULL, 화면 "도메인 노트"
    팝업에서 사용자가 런타임에 등록하는 값). domain_name을 안 주면(CLI/eval 등 app-db 접근이
    불필요한 호출부) ②는 건너뛴다.
    """
    parts: list[str] = []
    yaml_notes = (_load_yaml(prompt_fragments_path).get("notes") or "").strip()
    if yaml_notes:
        parts.append(yaml_notes)

    if domain_name:
        from app.domain.notes_store import list_notes  # 지연 임포트 — app.sql -> app.domain 순환 방지

        try:
            for row in list_notes(domain_name):
                if row["table_name"] is None and row["note"].strip():
                    parts.append(f"- {row['note'].strip()}")
        except Exception as e:
            logger.warning("domain_notes(app-db) 로드 실패 (domain=%s): %s", domain_name, e)

    return "\n".join(parts).strip()


def load_table_notes(prompt_fragments_path: Path, domain_name: str | None = None) -> dict[str, str]:
    """테이블별 참고사항을 읽는다 — {테이블명: 노트} dict.

    DB의 실제 COMMENT ON TABLE/COLUMN이 너무 일반적이라 스키마 임베딩(schema_indexer.py)만으로는
    비슷한 이름의 테이블을 구분 못 하는 경우, 또는 SQL 생성이 그 테이블의 코드값을 몰라 틀리는
    경우를 보완한다(EXP-017/EXP-018). 이 dict는 두 소비처 모두에 쓰인다 — schema_indexer.py가
    임베딩 텍스트에 덧붙이고, `render_table_notes_for_prompt()`가 SQL 생성 프롬프트용으로
    묶어준다. `load_general_notes`와 마찬가지로 YAML(개발 시점 기본값)과 app-db(사용자 등록,
    table_name IS NOT NULL)를 합친다 — 같은 테이블에 둘 다 있으면 app-db 값이 우선한다.
    """
    hints: dict[str, str] = {
        k: v.strip() for k, v in (_load_yaml(prompt_fragments_path).get("table_retrieval_hints") or {}).items() if v
    }

    if domain_name:
        from app.domain.notes_store import list_notes  # 지연 임포트 — app.sql -> app.domain 순환 방지

        try:
            for row in list_notes(domain_name):
                if row["table_name"] and row["note"].strip():
                    hints[row["table_name"]] = row["note"].strip()
        except Exception as e:
            logger.warning("domain_notes(app-db) 로드 실패 (domain=%s): %s", domain_name, e)

    return hints


def render_table_notes_for_prompt(table_notes: dict[str, str]) -> str:
    """테이블별 노트를 SQL 생성/schema_review 프롬프트에 넣을 텍스트 블록으로 렌더링한다."""
    if not table_notes:
        return ""
    lines = [f"- {table}: {note}" for table, note in sorted(table_notes.items())]
    return "\n".join(lines)


class SqlPromptBuilder:
    """스키마·예제·피드백·도메인 참고사항을 조합하여 SQL 생성 프롬프트를 만든다."""

    def __init__(self, domain_notes: str = ""):
        self._domain_notes = domain_notes

    def build(
        self,
        question:    str,
        schema_text: str,
        examples:    list[dict],
        feedback:    str | None  = None,
        error_code:  str | None  = None,
        task_type:   str         = "",
        metric:      str         = "",
        dimensions:  list[str]   | None = None,
        time_range:  dict        | None = None,
        type_guidance: str | None = None,
        prior_turn_context: str | None = None,
    ) -> str:
        parts = [_SYSTEM_PROMPT]

        if self._domain_notes:
            parts.append(f"\n\n[도메인 참고사항]\n{self._domain_notes}")

        parts.append("\n\n[스키마]\n" + schema_text)

        intent_lines: list[str] = []
        if task_type:
            intent_lines.append(f"task_type : {task_type}")
        if metric:
            intent_lines.append(f"metric    : {metric}")
        if dimensions:
            intent_lines.append(f"dimensions: {', '.join(dimensions)}")
        if time_range:
            from_  = time_range.get("from")  or "null"
            to_    = time_range.get("to")    or "null"
            grain  = time_range.get("grain") or "none"
            intent_lines.append(f"time_range: {from_} ~ {to_}  (grain={grain})")
        if intent_lines:
            parts.append("\n\n[의도 분석]\n" + "\n".join(intent_lines))

        if type_guidance:
            parts.append(f"\n\n[질의 유형 가이드]\n{type_guidance}")

        if examples:
            parts.append("\n\n[유사 예제]")
            for ex in examples:
                parts.append(
                    f"\n질문: {ex['question']}\n"
                    f"의도: {ex['intent']}\n"
                    f"SQL: {ex['canonical_sql']}"
                )

        if feedback:
            guide = _RETRY_GUIDE.get(error_code or "", "") if error_code else ""
            header = f"[재시도 — {error_code}]" if error_code else "[이전 시도 오류 — 반드시 수정 후 재작성하세요]"
            retry_block = f"\n\n{header}"
            if guide:
                retry_block += f"\n{guide}"
            retry_block += f"\n\n오류 내용:\n{feedback}"
            parts.append(retry_block)

        if prior_turn_context:
            parts.append(
                "\n\n[이전 턴 — 지금 질문이 여기 이어지는 후속 질문일 수 있습니다]\n"
                f"{prior_turn_context}\n"
                "위 이전 턴의 필터/조인 조건 중 지금 질문에서 부정되지 않은 부분은 그대로 유지하고,"
                " 지금 질문이 요구하는 부분만 바꿔서 SQL을 작성하세요."
            )

        parts.append(f"\n\n[질문]\n{question}\n\n[출력]")
        return "".join(parts)
