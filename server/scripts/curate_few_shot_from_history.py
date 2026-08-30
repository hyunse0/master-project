"""실행 히스토리에서 사람이 직접 SQL을 고쳐 승인한 run을 훑어보고, 골라서
domains/<domain>/few_shot.json에 추가한다.

교정 사례 학습 루프(docs/data-access-copilot-plan.md의 스트레치 골) 1단계 — 자동 승격이
아니라 사람이 "이 수정은 다음에도 참고할 만하다"고 직접 고르는 수동 큐레이션이다. 여기서
추가한 뒤에는 `python scripts/seed_few_shot.py --domain <name>`을 따로 돌려야 Qdrant
few-shot 컬렉션에 실제로 반영된다(이 스크립트는 JSON 파일만 갱신한다).

"Few-shot 예제 관리" 화면(app/api/fewshot_routes.py)이 생기면 같은 일을 화면에서 할 수
있다 — 이 스크립트는 화면 없이도 터미널에서 큐레이션할 수 있는 대안으로 남겨둔다. 둘 다
app/knowledge/few_shot_store.py를 거쳐 파일을 갱신하므로 결과물은 동일하다.

사용: python scripts/curate_few_shot_from_history.py --domain <name>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.knowledge import few_shot_store  # noqa: E402
from app.runs import run_manager  # noqa: E402


def _prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix} ").strip()
    return answer or default


def curate(domain_name: str) -> int:
    domain = get_domain(domain_name)
    already_added = {e["source_run_id"] for e in few_shot_store.list_entries(domain) if e.get("source_run_id")}
    candidates = [c for c in run_manager.list_edited_sql_runs(domain_name) if c["run_id"] not in already_added]
    if not candidates:
        print(f"[{domain_name}] 아직 few-shot으로 채택 안 된, 사람이 SQL을 고친 run이 없습니다.")
        return 0

    added = 0
    for c in candidates:
        print("\n" + "=" * 70)
        print(f"run_id      : {c['run_id']}  ({c['created_at']})")
        print(f"question    : {c['question']}")
        print(f"AI 원본 SQL : \n{c['sql_before_edit']}")
        print(f"사람 수정 SQL: \n{c['sql']}")
        print(f"수정 이유   : {c['correction_reason'] or '(입력 안 됨)'}")

        choice = _prompt("few_shot.json에 추가할까요? [y/N/q(중단)]", "n").lower()
        if choice == "q":
            break
        if choice != "y":
            continue

        few_shot_store.add_entry(
            domain,
            question=c["question"],
            intent=c["task_type"] or "",
            sql=c["sql"],
            tables=c["confirmed_schema"],
            source_run_id=c["run_id"],
            sql_before_edit=c["sql_before_edit"],
            correction_reason=c["correction_reason"],
        )
        added += 1

    return added


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    added = curate(args.domain)
    if added:
        print(
            f"\n[{args.domain}] {added}건을 few_shot.json에 추가했습니다. "
            f"Qdrant에 반영하려면 다음을 실행하세요:\n"
            f"  python scripts/seed_few_shot.py --domain {args.domain}"
        )
    else:
        print(f"\n[{args.domain}] 추가된 항목이 없습니다.")


if __name__ == "__main__":
    main()
