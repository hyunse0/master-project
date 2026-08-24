import logging
from dataclasses import dataclass, field

import psycopg2

from app.domain.loader import PostgresConnection

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    comment: str | None = None
    is_primary_key: bool = False


@dataclass
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    schema: str
    name: str
    comment: str | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"


class SchemaProvider:
    """접속된 Postgres에서 information_schema/pg_catalog로 스키마를 introspect한다.

    도메인 팩에 schema.yaml을 두지 않고 실제 DB에서 직접 읽는다 — "접속 정보만
    연결하면 스키마를 읽어 RAG를 구축한다"는 요구사항의 핵심 모듈.
    """

    def __init__(self, connection: PostgresConnection):
        self._conn_info = connection

    def _connect(self):
        c = self._conn_info
        return psycopg2.connect(host=c.host, port=c.port, dbname=c.dbname, user=c.user, password=c.password)

    def test_connection(self) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone() == (1,)
        finally:
            conn.close()

    def get_table_names(self) -> list[str]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE' "
                    "ORDER BY table_schema, table_name",
                    (self._conn_info.allowed_schemas,),
                )
                return [f"{schema}.{table}" for schema, table in cur.fetchall()]
        finally:
            conn.close()

    def get_table_info(self, schema: str, table: str) -> TableInfo:
        conn = self._connect()
        try:
            info = TableInfo(schema=schema, name=table)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pgd.description
                    FROM pg_catalog.pg_statio_all_tables st
                    LEFT JOIN pg_catalog.pg_description pgd
                        ON pgd.objoid = st.relid AND pgd.objsubid = 0
                    WHERE st.schemaname = %s AND st.relname = %s
                    """,
                    (schema, table),
                )
                row = cur.fetchone()
                info.comment = row[0] if row else None

                cur.execute(
                    """
                    SELECT c.column_name, c.data_type, pgd.description
                    FROM information_schema.columns c
                    LEFT JOIN pg_catalog.pg_statio_all_tables st
                        ON st.schemaname = c.table_schema AND st.relname = c.table_name
                    LEFT JOIN pg_catalog.pg_description pgd
                        ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
                    WHERE c.table_schema = %s AND c.table_name = %s
                    ORDER BY c.ordinal_position
                    """,
                    (schema, table),
                )
                columns = cur.fetchall()

                pk_columns = self._get_primary_key_columns(cur, schema, table)
                for name, data_type, comment in columns:
                    info.columns.append(ColumnInfo(
                        name=name, data_type=data_type, comment=comment,
                        is_primary_key=name in pk_columns,
                    ))

                cur.execute(
                    """
                    SELECT kcu.column_name, ccu.table_schema, ccu.table_name, ccu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_schema = %s AND tc.table_name = %s
                    """,
                    (schema, table),
                )
                for col, ref_schema, ref_table, ref_col in cur.fetchall():
                    info.foreign_keys.append(ForeignKeyInfo(
                        column=col, ref_table=f"{ref_schema}.{ref_table}", ref_column=ref_col,
                    ))
            return info
        finally:
            conn.close()

    @staticmethod
    def _get_primary_key_columns(cur, schema: str, table: str) -> set[str]:
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = %s AND tc.table_name = %s
            """,
            (schema, table),
        )
        return {r[0] for r in cur.fetchall()}

    def get_all_tables(self) -> list[TableInfo]:
        tables = []
        for full_name in self.get_table_names():
            schema, table = full_name.split(".", 1)
            tables.append(self.get_table_info(schema, table))
        return tables

    @staticmethod
    def table_to_text(table: TableInfo) -> str:
        lines = [f"테이블: {table.full_name}" + (f" — {table.comment}" if table.comment else "")]
        for col in table.columns:
            pk_marker = " [PK]" if col.is_primary_key else ""
            comment = f" — {col.comment}" if col.comment else ""
            lines.append(f"  {col.name}: {col.data_type}{pk_marker}{comment}")
        for fk in table.foreign_keys:
            lines.append(f"  FK: {fk.column} -> {fk.ref_table}.{fk.ref_column}")
        return "\n".join(lines)

    def get_schema_text(self, target_tables: list[str] | None = None) -> str:
        tables = self.get_all_tables()
        if target_tables:
            tables = [t for t in tables if t.full_name in target_tables or t.name in target_tables]
        return "\n\n".join(self.table_to_text(t) for t in tables)
