"""도메인 지식 노트를 app-db `domain_notes`에서 읽고 쓴다.

domain_connections/model_config와 같은 이유로 git 파일이 아니라 여기 저장 — 화면(도메인
관리 탭)에서 사용자가 런타임에 등록하는 값이다. table_name이 NULL이면 도메인 전체 공통
규칙, 값이 있으면 특정 테이블 전용 노트다. 그래프는 도메인당 한 번 빌드돼 캐싱되므로
(app/api/run_routes.py `_graph_cache`), 노트를 바꾼 뒤 반영하려면 그 캐시를 비워야 한다
(model_config.py와 동일 패턴 — 호출자인 domain_routes.py가 책임진다).

category(codeset/join/general)·structured_data는 화면이 노트를 구조화된 폼으로 편집하기
위한 원본 데이터일 뿐, 실제로 SQL 생성/스키마 임베딩이 읽는 값은 항상 note(최종 렌더링된
텍스트, 화면이 구조화 입력으로부터 합성)다 — 이 모듈과 app/sql/prompt_builder.py는
category가 무엇이든 note 컬럼만 다루므로, 새 category가 추가돼도 이 파일은 바뀌지 않는다.
"""
import json

from app.db.app_db import get_app_db_connection

_COLUMNS = "id, domain, table_name, category, structured_data, note, created_at, updated_at"


def list_notes(domain: str) -> list[dict]:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLUMNS} FROM domain_notes WHERE domain = %s "
                "ORDER BY category, table_name NULLS FIRST, created_at",
                (domain,),
            )
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def create_note(
    domain: str,
    table_name: str | None,
    note: str,
    category: str = "general",
    structured_data: dict | None = None,
) -> dict:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO domain_notes (domain, table_name, category, structured_data, note) "
                f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                (domain, table_name, category, json.dumps(structured_data) if structured_data is not None else None, note),
            )
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, cur.fetchone()))
    finally:
        conn.close()


def update_note(note_id: str, note: str, structured_data: dict | None = None) -> dict | None:
    """note 텍스트(+구조화 데이터가 있으면 함께)를 갱신한다. category/table_name은 생성 시
    고정 — 카테고리를 바꾸고 싶으면 삭제 후 새로 등록한다(폼 모양 자체가 달라지므로)."""
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE domain_notes SET note = %s, structured_data = %s, updated_at = now() "
                f"WHERE id = %s RETURNING {_COLUMNS}",
                (note, json.dumps(structured_data) if structured_data is not None else None, note_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, row))
    finally:
        conn.close()


def delete_note(note_id: str) -> bool:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM domain_notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0
    finally:
        conn.close()
