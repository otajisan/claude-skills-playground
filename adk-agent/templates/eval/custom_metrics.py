"""カスタムメトリクスの例（第 5 章 5.2.6）。eval_config.custom_example.json から参照される。

ADK v2.2.0 では eval_config.json の custom_metrics.<name>.code_config.name に
"<module_path>.<function_name>" を指定すると CustomMetricEvaluator が importlib で読み込む。
閾値は eval_metric.criterion.threshold から取る（eval_metric.threshold は None にされる）。
"""

from __future__ import annotations

import re
from typing import Optional

from google.adk.evaluation.eval_case import ConversationScenario, Invocation
from google.adk.evaluation.eval_metrics import EvalMetric
from google.adk.evaluation.evaluator import EvalStatus, EvaluationResult, PerInvocationResult

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _text(invocation: Invocation) -> str:
    content = getattr(invocation, "final_response", None)
    if not content or not content.parts:
        return ""
    return "".join(part.text or "" for part in content.parts if getattr(part, "text", None))


def _numbers(text: str) -> list[float]:
    return [float(n) for n in _NUMBER.findall(text.replace(",", ""))]


def domain_accuracy(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]],
    conversation_scenario: Optional[ConversationScenario] = None,
) -> EvaluationResult:
    """応答内の数値を参照応答と照合する（許容誤差 1%）。"""
    threshold = (
        eval_metric.criterion.threshold
        if eval_metric.criterion and eval_metric.criterion.threshold is not None
        else 0.8
    )
    per_invocation: list[PerInvocationResult] = []
    expected_invocations = expected_invocations or []

    for actual, expected in zip(actual_invocations, expected_invocations):
        expected_numbers = _numbers(_text(expected))
        actual_numbers = _numbers(_text(actual))
        if not expected_numbers:
            score = 1.0  # 数値の無いケースは対象外として満点
        else:
            matched = sum(
                1
                for e in expected_numbers
                if any(abs(a - e) <= abs(e) * 0.01 for a in actual_numbers)
            )
            score = matched / len(expected_numbers)
        per_invocation.append(
            PerInvocationResult(
                actual_invocation=actual,
                expected_invocation=expected,
                score=score,
                eval_status=EvalStatus.PASSED if score >= threshold else EvalStatus.FAILED,
            )
        )

    overall = sum(r.score for r in per_invocation) / len(per_invocation) if per_invocation else 0.0
    return EvaluationResult(
        overall_score=overall,
        overall_eval_status=EvalStatus.PASSED if overall >= threshold else EvalStatus.FAILED,
        per_invocation_results=per_invocation,
    )
