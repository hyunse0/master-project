"""golden_set.json 기반 스키마 매핑(schema_linking) 정확도 평가.
사용: python eval/schema_mapping_accuracy.py --domain <name>

execution_accuracy.py가 "최종 SQL이 맞는 답을 내는지"를 재는 반면, 이 스크립트는
"SQL이 틀리더라도 schema_linking이 애초에 옳은 테이블을 골랐는지"만 따로 잰다 —
파이프라인 중간 단계(스키마 링킹)의 품질을 SQL 생성 실패와 분리해서 보기 위함
(data-access-copilot-plan.md H단계).

golden_set.json 포맷은 execution_accuracy.py와 동일: [{"question": "...", "expected_sql": "..."}, ...]
"expected_sql"이 참조하는 테이블 집합을 정답으로 삼고, graph 실행 결과의 confirmed_schema
(자동 모드에선 schema_linking이 고른 후보가 그대로 확정됨)와 비교해 질문별 precision/recall/f1을 낸다.
아직 golden_set.json이 없는 도메인은 스킵 메시지만 출력하고 정상 종료한다.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import sqlglot
import sqlglot.expressions as exp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.observability import run_logger  # noqa: E402


def _extract_tables(sql: str) -> set[str]:
    """SQL이 참조하는 테이블을 "schema.table" 소문자 집합으로 뽑는다.

    app/sql/schema_provider.py의 TableInfo.full_name("schema.table")과 같은 형식으로
    맞춰야 confirmed_schema(스키마 인덱서가 그 형식으로 색인한 값)와 직접 비교 가능하다.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return set()
    return {
        f"{(t.db or 'public')}.{t.name}".lower()
        for t in tree.find_all(exp.Table)
        if t.name
    }


def _prf1(expected: set[str], predicted: set[str]) -> tuple[float, float, float]:
    if not predicted and not expected:
        return 1.0, 1.0, 1.0
    intersection = expected & predicted
    precision = len(intersection) / len(predicted) if predicted else 0.0
    recall = len(intersection) / len(expected) if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    domain = get_domain(args.domain)
    if not domain.golden_set_path.is_file():
        print(f"[{args.domain}] golden_set.json 없음 ({domain.golden_set_path}) — 스킵")
        return

    golden = json.loads(domain.golden_set_path.read_text())
    if not golden:
        print("골든셋이 비어있습니다.")
        return

    graph = build_graph(domain)

    sum_p = sum_r = sum_f1 = 0.0
    for item in golden:
        run_id = str(uuid.uuid4())
        state = graph.invoke(
            {
                "question": item["question"],
                "domain": domain.name,
                "run_id": run_id,
                "tags": {"experiment": "schema_mapping_accuracy"},
                "review_config": {"schema": False, "sql": False},
            },
            config={"recursion_limit": 50},
        )

        expected = _extract_tables(item["expected_sql"])
        predicted = {t.lower() for t in (state.get("confirmed_schema") or [])}
        precision, recall, f1 = _prf1(expected, predicted)
        sum_p += precision
        sum_r += recall
        sum_f1 += f1

        print(
            f"  [P={precision:.2f} R={recall:.2f} F1={f1:.2f}] {item['question']}"
            f"\n      expected={sorted(expected)} predicted={sorted(predicted)}"
        )

        run_logger.log(
            run_id=run_id,
            domain=domain.name,
            question=item["question"],
            status="success" if f1 == 1.0 else "error",
            tags={
                "experiment": "schema_mapping_accuracy",
                "difficulty": state.get("difficulty"),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            },
        )

    total = len(golden)
    print(
        f"\nSchema Mapping Accuracy (n={total}): "
        f"precision={sum_p / total:.1%}  recall={sum_r / total:.1%}  f1={sum_f1 / total:.1%}"
    )


if __name__ == "__main__":
    main()
