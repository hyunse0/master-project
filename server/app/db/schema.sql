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

-- 노드별 LLM 호출 1건당 토큰 사용량. run_id는 runs.run_id를 참조할 수도, CLI/eval 실행처럼
-- registry가 없는 ad-hoc uuid일 수도 있어 FK는 걸지 않는다.
-- tags가 KPI 비교의 핵심 — 예: {"schema_rag_mode":"rag"} vs {"schema_rag_mode":"full_dump"}로
-- 태깅해 GROUP BY tags->>'schema_rag_mode'로 전/후 비교한다 (data-access-copilot-plan.md 참고,
-- B단계 KPI 인프라 추가분).
CREATE TABLE IF NOT EXISTS token_usage (
  id            BIGSERIAL PRIMARY KEY,
  run_id        UUID,
  node          TEXT NOT NULL,
  model         TEXT NOT NULL,
  input_tokens  INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  tags          JSONB NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS token_usage_run_idx  ON token_usage (run_id);
CREATE INDEX IF NOT EXISTS token_usage_tags_idx ON token_usage USING GIN (tags);

-- 그래프 1회 실행(invoke)의 결과 요약. 정확도/성공률/재시도횟수 같은 "답변 품질" 축.
CREATE TABLE IF NOT EXISTS run_metrics (
  id          BIGSERIAL PRIMARY KEY,
  run_id      UUID,
  domain      TEXT NOT NULL,
  question    TEXT NOT NULL,
  status      TEXT NOT NULL,
  error_code  TEXT,
  retries     INTEGER NOT NULL DEFAULT 0,
  row_count   INTEGER,
  sql         TEXT,
  latency_ms  INTEGER,
  tags        JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS run_metrics_tags_idx ON run_metrics USING GIN (tags);
