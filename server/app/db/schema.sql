-- app-db 스키마. LangGraph PostgresSaver의 체크포인트 테이블(checkpoints,
-- checkpoint_writes, checkpoint_blobs 등)은 여기 포함하지 않는다 — C그룹(human-in-the-loop)
-- 구현 시 `PostgresSaver.setup()`이 알아서 만든다. 여기는 그 외 앱이 직접 관리하는 테이블만.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- run 존재 여부·상태 캐시. 진실은 PostgresSaver 체크포인트에 있고, 이 테이블은
-- 실행 히스토리 화면이 목록을 빠르게 조회하기 위한 레지스트리다.
-- (data-access-copilot-plan.md 5번 섹션 3번 항목 참고)
CREATE TABLE IF NOT EXISTS runs (
  run_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain        TEXT NOT NULL,
  question      TEXT NOT NULL,
  review_config JSONB NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'running',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS runs_domain_created_idx ON runs (domain, created_at DESC);

-- 타겟 도메인 접속정보. 실서비스에서는 사용자가 화면으로 직접 입력하는 값이라 .env가 아니라
-- 여기 저장한다. db_password_enc는 평문이 아니라 app/db/encryption.py(Fernet, APP_SECRET_KEY)로
-- 암호화된 바이트 — 앱 레벨에서 암복호화하며, DB 안에서 키를 다루지 않는다(쿼리 로그 노출 방지).
CREATE TABLE IF NOT EXISTS domain_connections (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL UNIQUE,
  db_host         TEXT NOT NULL,
  db_port         INTEGER NOT NULL DEFAULT 5432,
  db_name         TEXT NOT NULL,
  db_user         TEXT NOT NULL,
  db_password_enc BYTEA NOT NULL,
  db_schemas      TEXT[] NOT NULL DEFAULT '{public}',
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 에이전트가 동시에 쓰는 도메인은 항상 최대 1개 — 화면/코드가 아니라 제약으로 강제
CREATE UNIQUE INDEX IF NOT EXISTS one_active_domain ON domain_connections (is_active) WHERE is_active;
