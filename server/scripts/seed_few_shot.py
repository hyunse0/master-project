"""domains/<domain>/few_shot.json을 읽어 Qdrant sql_knowledge_{domain} 컬렉션에 색인한다.

멱등 — 매번 컬렉션을 통째로 지우고 JSON 파일 내용으로 다시 채운다. few_shot.json이
소스 오브 트루스이므로 몇 번을 다시 돌려도 중복이 쌓이지 않는다. 실제 로직은
app/knowledge/few_shot_seeder.py에 있다 — "Few-shot 예제 관리" 화면의 [Qdrant에 반영]
버튼도 같은 함수를 호출한다.

사용: python scripts/seed_few_shot.py --domain <name>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.knowledge.few_shot_seeder import seed_domain  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    count = seed_domain(args.domain)
    domain = get_domain(args.domain)
    print(f"[{args.domain}] {count}건을 few-shot 컬렉션({domain.qdrant_fewshot_collection})에 저장했습니다.")


if __name__ == "__main__":
    main()
