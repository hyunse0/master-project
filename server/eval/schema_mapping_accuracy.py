"""golden_set.json 기반 스키마 매핑(schema_linking) 정확도 평가.
사용: python eval/schema_mapping_accuracy.py --domain <name>

execution_accuracy.py가 "최종 SQL이 맞는 답을 내는지"를 재는 반면, 이건 "SQL이 틀리더라도
schema_linking이 애초에 옳은 테이블을 골랐는지"만 따로 잰다 — 파이프라인 중간 단계(스키마
링킹)의 품질을 SQL 생성 실패와 분리해서 보기 위함(data-access-copilot-plan.md H단계).

두 지표 다 같은 golden_set.json을 graph.invoke()에 태워서 나온 state에서 뽑아낼 수 있어서,
실제 평가 로직은 execution_accuracy.run()이 한 번의 실행으로 두 experiment 태그를 모두
run_metrics에 남긴다(질문당 LLM을 두 번 태우지 않으려는 목적) — 이 스크립트는 그 결과 중
schema mapping 부분만 CLI에 보여주는 얇은 래퍼다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from eval.execution_accuracy import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    domain = get_domain(args.domain)
    result = run(domain)

    if result["skipped"]:
        if result["reason"] == "golden_set_missing":
            print(f"[{args.domain}] golden_set.json 없음 ({domain.golden_set_path}) — 스킵")
        else:
            print("골든셋이 비어있습니다.")
        return

    sm = result["schema_mapping"]
    print(
        f"Schema Mapping Accuracy (n={result['total']}): "
        f"precision={sm['precision']:.1%}  recall={sm['recall']:.1%}  f1={sm['f1']:.1%}"
    )
    print("(질문별 상세는 execution_accuracy.py 실행 로그를 참고하세요 — 같은 실행에서 함께 계산됩니다.)")


if __name__ == "__main__":
    main()
