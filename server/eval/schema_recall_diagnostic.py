"""EXP-014 진단 스크립트 — Schema Retrieval Recall과 Schema Review Retention의 병목 분리.

golden_set.json 각 턴에 대해 graph.invoke()를 한 번 돌려 다음 세 집합을 비교한다:
  - gold_tables: expected_sql을 sqlglot으로 파싱해 뽑은 정답 테이블 집합
  - schema_candidates: schema_linking_node가 만든 top-5 벡터 검색 결과(review 이전)
  - confirmed_schema: schema_review_node가 LLM으로 재선정한 최종 테이블(review 이후)

각 턴을 세 유형으로 분류한다(질문당 하나):
  - retrieval_miss: gold_tables 중 schema_candidates에 없는 테이블이 있음 (schema_linking 문제)
  - review_miss: gold_tables ⊆ schema_candidates 지만 gold_tables ⊄ confirmed_schema
                 (schema_review가 검색된 정답 후보를 탈락시킴)
  - schema_ok: gold_tables ⊆ confirmed_schema (스키마 단계는 성공 — 오답이면 SQL 생성 문제)

schema_ok로 분류된 턴 중 실제 생성 SQL이 gold_tables를 전부 참조하지 않으면 별도로
"schema_ok_but_sql_dropped_table"로 세어, "테이블은 확보했는데 SQL이 안 썼다"는 세 번째
실패 지점(조인 구성 실패)까지 구분한다 — EXP-013에서 두 케이스(스키마 단계 vs SQL 생성 단계)를
구분 못 했던 것을 보완한다.

사용: python eval/schema_recall_diagnostic.py --domain poc_prostate
관측만 하고 아무것도 바꾸지 않는 진단 실행이라 run_logger에 남기지 않는다(execution_accuracy.py와
달리 KPI로 추적할 지표가 아니라 다음 실험 방향을 정하기 위한 1회성 분해 분석).
"""
import argparse
import json
import sys
from pathlib import Path

import sqlglot
import sqlglot.expressions as exp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.graph.conversation_context import extract_prior_turn  # noqa: E402


def _extract_tables(sql: str) -> set[str]:
    """SQL이 참조하는 실제 테이블 집합. WITH절 CTE 이름은 sqlglot이 exp.Table로도 잡아내므로
    (예: `WITH counts AS (...) SELECT ... FROM counts`의 `counts`), CTE 별칭 목록을 뽑아
    제외한다 — 안 그러면 gold_tables에 존재하지 않는 가짜 "테이블"이 섞여 모든 비교가 항상
    retrieval_miss로 오분류된다."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return set()
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    return {
        f"{(t.db or 'public')}.{t.name}".lower()
        for t in tree.find_all(exp.Table)
        if t.name and t.name.lower() not in cte_names
    }


def classify(gold: set[str], candidates: set[str], confirmed: set[str], used_by_sql: set[str]) -> str:
    if not gold.issubset(candidates):
        return "retrieval_miss"
    if not gold.issubset(confirmed):
        return "review_miss"
    if not gold.issubset(used_by_sql):
        return "schema_ok_but_sql_dropped_table"
    return "schema_ok"


def run(domain_name: str) -> dict:
    domain = get_domain(domain_name)
    golden = json.loads(domain.golden_set_path.read_text())
    graph = build_graph(domain)

    rows = []
    for conv_idx, conv in enumerate(golden, start=1):
        conversation_id = f"diag-{conv_idx}"
        prior_turns: list[dict] = []
        for turn_no, item in enumerate(conv["turns"], start=1):
            import uuid

            state = graph.invoke(
                {
                    "question": item["question"],
                    "domain": domain.name,
                    "run_id": str(uuid.uuid4()),
                    "tags": {"experiment": "schema_recall_diagnostic", "turn_no": turn_no},
                    "review_config": {"schema": False, "sql": False},
                    "conversation_id": conversation_id,
                    "turn_no": turn_no,
                    "carry_schema": False,
                    "prior_turns": prior_turns,
                },
                config={"recursion_limit": 50},
            )

            gold = _extract_tables(item["expected_sql"])
            candidates = {t.lower() for t in (state.get("schema_candidates") or [])}
            confirmed = {t.lower() for t in (state.get("confirmed_schema") or [])}
            generated_sql = state.get("sql") or ""
            used_by_sql = _extract_tables(generated_sql) if generated_sql else set()

            category = classify(gold, candidates, confirmed, used_by_sql)
            rows.append({
                "conv": conv_idx,
                "turn_no": turn_no,
                "question": item["question"],
                "gold": sorted(gold),
                "candidates": sorted(candidates),
                "confirmed": sorted(confirmed),
                "used_by_sql": sorted(used_by_sql),
                "category": category,
            })

            turn_succeeded = bool(generated_sql) and not state.get("execution_error") and state.get("retry_error_code") is None
            prior_turns = [extract_prior_turn(item["question"], state)] if turn_succeeded else []

    total = len(rows)
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1

    retrieval_recall = sum(1 for r in rows if r["category"] != "retrieval_miss") / total
    among_retrieved = [r for r in rows if r["category"] != "retrieval_miss"]
    review_retention = (
        sum(1 for r in among_retrieved if r["category"] != "review_miss") / len(among_retrieved)
        if among_retrieved else None
    )
    end_to_end_schema_recall = sum(
        1 for r in rows if r["category"] in ("schema_ok", "schema_ok_but_sql_dropped_table")
    ) / total

    return {
        "total": total,
        "counts": counts,
        "retrieval_recall": retrieval_recall,
        "review_retention": review_retention,
        "end_to_end_schema_recall": end_to_end_schema_recall,
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--verbose", action="store_true", help="턴별 상세(gold/candidates/confirmed) 출력")
    args = parser.parse_args()

    result = run(args.domain)

    print(f"\n총 {result['total']}턴")
    for cat, n in sorted(result["counts"].items()):
        print(f"  {cat}: {n} ({n / result['total']:.1%})")

    print(f"\nRetrieval Recall (gold ⊆ schema_candidates 비율): {result['retrieval_recall']:.1%}")
    if result["review_retention"] is not None:
        print(f"Review Retention (검색된 정답 중 review 이후에도 남은 비율): {result['review_retention']:.1%}")
    print(f"End-to-end Schema Recall (gold ⊆ confirmed_schema 비율): {result['end_to_end_schema_recall']:.1%}")

    if args.verbose:
        print("\n--- 턴별 상세 ---")
        for r in result["rows"]:
            print(f"\n[{r['category']}] conv{r['conv']} turn{r['turn_no']}: {r['question']}")
            print(f"  gold:       {r['gold']}")
            print(f"  candidates: {r['candidates']}")
            print(f"  confirmed:  {r['confirmed']}")
            if r["category"] == "schema_ok_but_sql_dropped_table":
                print(f"  used_by_sql: {r['used_by_sql']}")


if __name__ == "__main__":
    main()
