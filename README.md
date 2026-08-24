# Data Access Copilot

자연어 질의를 스키마 링킹 → SQL 생성 → 검증 → 실행으로 처리하는 NL2SQL 에이전트. 접속 정보만 주면 Postgres 스키마를 읽어 RAG를 구축하는 범용 커넥터를 기반으로 한다.

## 사전 준비

- Docker
- Python 3.11+
- Node.js 18+

## 빠른 시작

### 1. 인프라 (Postgres + Qdrant)

```bash
docker compose up -d
```

`postgres` 서비스엔 이미 `poc_prostate` 데모 도메인(전립선암 PoC 스키마·샘플데이터·컬럼 코멘트)이 적용돼 있다. 처음부터 다시 세팅하는 방법은 `docs/data-access-copilot-plan.md`의 "A. 데이터 계층" 참고.

### 2. 백엔드

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 이미 있으면 생략 — APP_SECRET_KEY는 아래 명령으로 채우기
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # 이 값을 .env의 APP_SECRET_KEY=에 붙여넣기

python scripts/init_app_db.py   # app-db 스키마 적용 (runs, domain_connections)
python scripts/register_domain.py --name poc_prostate --host localhost --port 5432 \
  --dbname poc_prostate --user postgres --password postgres --schemas poc --activate

uvicorn app.main:app --reload --port 8000
```

도메인 접속정보(`domain_connections` 테이블에 저장, 비밀번호는 암호화)는 더 이상 `.env`가 아니라 `register_domain.py`로 등록한다 — 실서비스에서 사용자가 화면으로 입력할 값이라 DB에 둔다. 자세한 배경은 `docs/data-access-copilot-plan.md`의 5번 섹션 참고.

### 3. 프론트엔드

```bash
cd client
npm install
npm run dev
```

브라우저에서 http://localhost:5173 접속.

## 동작 확인

```bash
curl http://localhost:8000/health           # API 헬스체크
curl http://localhost:8000/domain/status    # 연결된 도메인 상태
```

## 프로젝트 구조

```
server/     FastAPI + LangGraph 백엔드
client/     React 프론트엔드 (Vite)
docs/       설계 문서
docker-compose.yml   Postgres(데모 도메인) + Qdrant + app-db(앱 운영 데이터)
```

## 더 알아보기

- 전체 구현 계획: [docs/data-access-copilot-plan.md](docs/data-access-copilot-plan.md)
- 화면 설계 브리프: [docs/screen-spec.html](docs/screen-spec.html)
