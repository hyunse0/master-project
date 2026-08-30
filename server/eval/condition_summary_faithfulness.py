"""execution 노드가 만드는 자연어 요약(## 요약)이 실제 쿼리 결과를 벗어난 내용을
지어내지 않았는지 LLM judge로 판정한다.
사용: python eval/condition_summary_faithfulness.py --domain <name> [--limit N]

golden_set.json(정답 SQL)이 필요 없다 — benchmark_queries.json(질문만 있음)을 그대로 써서
"결과가 요약문과 부합하는가"만 보기 때문에, 정답이 뭔지 몰라도 판정 가능하다
(data-access-copilot-plan.md H단계, condition_summary_faithfulness.py).

판정은 LLM judge 방식: {question, columns, rows, 요약문}을 저비용 모델에 주고
{"faithful": true|false, "reason": "..."}로 응답받는다. 규칙 기반(숫자 매칭)보다 비용은
들지만 잘못된 항목/방향성 오류까지 잡아낼 수 있어 이 방식을 택함(사용자 확인 완료).

extract_summary_section()/judge_faithfulness()는 execution_accuracy.run()도 그대로
가져다 쓴다 — golden_set.json 기준 "지금 실행"이 그래프를 이미 돌린 김에 같은 state로
요약 충실도까지 함께 판정해서 그래프 재실행(=LLM 재호출) 없이 세 지표를 한 번에 낸다.
이 스크립트 자체는 golden_set.json 없이 benchmark_queries.json만으로도 독립적으로 계속
동작한다 — 골든셋이 없는 도메인에서도 요약 충실도만은 잴 수 있어야 하기 때문.
"""
import argparse
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.llm.base import TokenCountingLLM  # noqa: E402
from app.llm.router import build_llm_router  # noqa: E402
from app.observability import run_logger  # noqa: E402

_JUDGE_PROMPT = """\
당신은 NL2SQL 응답 감사관입니다. 아래 "요약문"이 "쿼리 결과"에 없는 수치·항목·주장을
지어내지 않았는지만 판정하세요. 결과에 실제로 있는 내용을 문장으로 재구성한 것은
faithful=true입니다. 결과에 없는 숫자를 인용했거나, 결과와 반대되는 주장을 하거나,
결과에 없는 항목을 언급했다면 faithful=false입니다.

질문: {question}
쿼리 결과 컬럼: {columns}
쿼리 결과 전체 건수: {row_count}
쿼리 결과 미리보기(최대 20건):
{rows_text}

요약문:
{summary_text}

아래 JSON 형식만 반환하세요. 설명이나 마크다운 없이 JSON만.
{{"faithful": true|false, "reason": "한 문장으로 판정 근거"}}
"""


def extract_summary_section(full_summary: str) -> str:
    """execution 노드가 조립한 "## 요약\\n...\\n## SQL\\n..." 블록에서 요약 부분만 뽑는다.

    ## SQL/## 결과 블록까지 judge에게 그대로 주면 결과 원문이 요약문 안에 있는 것처럼
    보여 판정이 무의미해지므로, judge에는 요약 문장만 넘긴다.
    """
    match = re.search(r"##\s*요약\s*\n(.*?)(?=\n##\s|\Z)", full_summary, re.DOTALL)
    return match.group(1).strip() if match else full_summary.strip()


def _rows_text(columns: list[str], rows: list[dict], limit: int = 20) -> str:
    if not rows or not columns:
        return "(결과 없음)"
    sample = rows[:limit]
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in columns) + " |" for r in sample)
    return f"{header}\n{sep}\n{body}"


def judge_faithfulness(llm: TokenCountingLLM, run_id: str, question: str, columns: list[str], rows: list[dict], summary_text: str) -> dict:
    prompt = _JUDGE_PROMPT.format(
        question=question,
        columns=", ".join(columns),
        row_count=len(rows),
        rows_text=_rows_text(columns, rows),
        summary_text=summary_text,
    )
    raw = llm.generate(prompt, run_id=run_id, node="faithfulness_judge", tags={"experiment": "condition_summary_faithfulness"})
    text = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(text)
        return {"faithful": bool(data.get("faithful")), "reason": data.get("reason", "")}
    except Exception as e:
        return {"faithful": None, "reason": f"judge 응답 파싱 실패: {e} / raw={raw[:200]}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--limit", type=int, default=None, help="검사할 질문 수 제한(기본 전체)")
    args = parser.parse_args()

    domain = get_domain(args.domain)
    if not domain.benchmark_queries_path.is_file():
        print(f"[{args.domain}] benchmark_queries.json 없음 ({domain.benchmark_queries_path}) — 스킵")
        return

    queries = json.loads(domain.benchmark_queries_path.read_text())
    if args.limit:
        queries = queries[: args.limit]

    graph = build_graph(domain)
    # 판정 자체도 비용이 드는 LLM 호출이라 저비용 티어를 쓴다 — app/llm/router.py의
    # 난이도별 티어 매핑 중 "easy"가 가리키는 저비용 클라이언트를 그대로 재사용.
    judge_llm = build_llm_router()["easy"]

    total = faithful_count = 0
    failures: list[dict] = []
    for q in queries:
        run_id = str(uuid.uuid4())
        state = graph.invoke(
            {
                "question": q["question"],
                "domain": domain.name,
                "run_id": run_id,
                "tags": {"experiment": "condition_summary_faithfulness"},
                "review_config": {"schema": False, "sql": False},
            },
            config={"recursion_limit": 50},
        )

        row_count = state.get("row_count")
        if row_count is None or state.get("execution_error"):
            print(f"  [SKIP] {q['question']} — 파이프라인 실행 실패(요약 자체가 없음)")
            continue

        summary_text = extract_summary_section(state.get("summary") or "")
        verdict = judge_faithfulness(judge_llm, run_id, q["question"], state.get("columns") or [], state.get("rows") or [], summary_text)

        if verdict["faithful"] is None:
            print(f"  [ERR ] {q['question']} — {verdict['reason']}")
            continue

        total += 1
        faithful_count += int(verdict["faithful"])
        tag = "OK" if verdict["faithful"] else "FAIL"
        print(f"  [{tag}] {q['question']} — {verdict['reason']}")
        if not verdict["faithful"]:
            failures.append({"question": q["question"], "summary": summary_text, "reason": verdict["reason"]})

        # summary/columns/rows도 tags에 남긴다 — Golden Set 평가 화면이 실패 사례를 펼쳤을 때
        # 판정 근거가 된 실제 요약문·결과를 다시 보여줄 수 있어야 하기 때문(rows는 5건만 저장).
        run_logger.log(
            run_id=run_id,
            domain=domain.name,
            question=q["question"],
            status="success",
            row_count=row_count,
            sql=state.get("sql"),
            tags={
                "experiment": "condition_summary_faithfulness",
                "faithful": verdict["faithful"],
                "reason": verdict["reason"],
                "summary": summary_text,
                "columns": state.get("columns") or [],
                "rows": (state.get("rows") or [])[:5],
            },
        )

    if total == 0:
        print("\n판정 가능한 질문이 없습니다.")
        return

    print(f"\nCondition Summary Faithfulness: {faithful_count}/{total} ({faithful_count / total:.1%})")
    if failures:
        print("\n실패 사례:")
        for f in failures:
            print(f"  - {f['question']}\n    reason: {f['reason']}")


if __name__ == "__main__":
    main()
