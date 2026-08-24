import psycopg2

from app.domain.loader import PostgresConnection


def get_domain_connection(connection: PostgresConnection):
    """대상 도메인 DB(질의 실행 대상)에 접속한다.

    schema_provider._connect()와 같은 접속 로직을 공용 헬퍼로 분리한 것 — value_anchor,
    schema_citation_validator, execution 노드가 실제 쿼리를 던질 때 공통으로 사용한다.
    """
    return psycopg2.connect(
        host=connection.host,
        port=connection.port,
        dbname=connection.dbname,
        user=connection.user,
        password=connection.password,
    )
