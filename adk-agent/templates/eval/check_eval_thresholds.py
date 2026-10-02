#!/usr/bin/env python3
"""adk eval の出力ログから各メトリクスのスコアを抽出し、閾値未達なら終了コード 1 を返す（CI 用）。

使い方:
    adk eval ./my_agent eval/eval_set.json --config_file_path eval/eval_config.json \
        --print_detailed_results | tee eval_results/output.log
    python eval/check_eval_thresholds.py eval_results/ [--config eval/eval_config.json]

adk eval 自体も FAIL 時に終了コード 1 を返すが、本スクリプトは「どのメトリクスがどれだけ
下回ったか」を CI ログに残し、閾値をコードで一元管理するためのもの。
出力フォーマットは ADK バージョンで変わり得るため、抽出できないメトリクスは警告して継続する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_THRESHOLDS = {
    "tool_trajectory_avg_score": 0.8,
    "response_match_score": 0.7,
    "response_evaluation_score": 3.5,
}

SCORE_PATTERN = re.compile(r"(?P<metric>[a-z_]+_score(?:_v\d+)?)\s*[:=]\s*(?P<score>\d+(?:\.\d+)?)")


def load_thresholds(config_path: Path | None) -> dict[str, float]:
    if config_path is None or not config_path.exists():
        return dict(DEFAULT_THRESHOLDS)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    criteria = data.get("criteria", {})
    thresholds: dict[str, float] = {}
    for name, value in criteria.items():
        if isinstance(value, dict):  # {"threshold": 0.8, "match_type": ...} 形式
            if "threshold" in value:
                thresholds[name] = float(value["threshold"])
        else:
            thresholds[name] = float(value)
    return thresholds or dict(DEFAULT_THRESHOLDS)


def collect_scores(results_dir: Path) -> dict[str, list[float]]:
    scores: dict[str, list[float]] = {}
    for path in sorted(results_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".log", ".txt", ".json"}:
            continue
        for match in SCORE_PATTERN.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            scores.setdefault(match.group("metric"), []).append(float(match.group("score")))
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description="adk eval の結果を閾値で判定する")
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--config", type=Path, default=None, help="eval_config.json（criteria から閾値を読む）")
    args = parser.parse_args()

    thresholds = load_thresholds(args.config)
    scores = collect_scores(args.results_dir)
    if not scores:
        print(f"[ERROR] {args.results_dir} からスコアを抽出できませんでした。adk eval の出力を保存しているか確認してください。")
        return 1

    failed = False
    for metric, threshold in thresholds.items():
        values = scores.get(metric)
        if not values:
            print(f"[WARN] {metric}: 出力に見つかりません（閾値 {threshold}）")
            continue
        minimum = min(values)
        status = "OK  " if minimum >= threshold else "FAIL"
        if minimum < threshold:
            failed = True
        print(f"[{status}] {metric}: min={minimum:.3f} avg={sum(values)/len(values):.3f} (n={len(values)}, threshold={threshold})")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
