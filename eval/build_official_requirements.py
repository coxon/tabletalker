"""Build a synthetic Public_Analysis_Requirements.jsonl from cases-20.yaml.

The organizer's hidden requirements file isn't available pre-submission —
we don't get to validate the offline-fallback path against a real grader
input. This script reverses the conversion so we can sanity-check the
parser, runner, and bundle output end-to-end with a file shaped exactly
like what 赛题4 §4.1 / §4.2 specifies.

Mapping:
    case_id              → id (with a `eval_analysis_` prefix)
    case.question        → user_query, type=standard_analysis
    case.followup        → SKIPPED (§4.2 says follow-ups are interactive,
                           not part of the offline batch path)
    case.trap.question   → user_query, type=unanswerable, second line
    case.primary_file    → file (preserved for our extension)
    case.extra_files     → extra_files (preserved)

Output: eval/official_requirements_sample.jsonl

Usage:
    python eval/build_official_requirements.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases-20.yaml"
OUT = ROOT / "official_requirements_sample.jsonl"


def main() -> None:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    lines: list[str] = []
    for case in cases:
        case_id = case["id"]
        primary = case.get("primary_file") or f"{case_id}.csv"
        extras = list(case.get("extra_files") or [])
        # 1. The standard_analysis line for the main question.
        lines.append(
            json.dumps(
                {
                    "id": f"eval_analysis_{case_id}",
                    "type": "standard_analysis",
                    "dataset": case_id,
                    "user_query": case["question"],
                    "file": primary,
                    "extra_files": extras,
                },
                ensure_ascii=False,
            )
        )
        # 2. The unanswerable trap line, when the case carries one. The
        #    organizer's §4.2 example uses `expected_behavior` and
        #    `acceptable_response_keywords` — we synthesise the latter
        #    from the canonical refusal phrasings so the bundle round-
        #    trip exercises that field too.
        trap = case.get("trap")
        if trap:
            lines.append(
                json.dumps(
                    {
                        "id": f"eval_trap_{case_id}",
                        "type": "unanswerable",
                        "dataset": case_id,
                        "user_query": trap["question"],
                        "file": primary,
                        "extra_files": extras,
                        "expected_behavior": (
                            "refuse_with_reason"
                            if trap.get("expected_refusal", True)
                            else "answer"
                        ),
                        "acceptable_response_keywords": [
                            "数据集中不包含",
                            "无法基于",
                            "没有相关字段",
                            "建议补充",
                        ],
                        "forbidden_keywords": ["确实存在", "可以这样分析"],
                    },
                    ensure_ascii=False,
                )
            )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} lines to {OUT.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
