"""Offline accuracy check for the triage rules.

Design note: docs/architecture/agents/TRIAGE_RULES_AND_QUICK_TEAM.md. Runs the
deterministic rules over triage_golden.json. No network, no model and no database.
Requests the rules decline to decide would go to the cheap model in a real run;
here they are scored as Standard, which is what offline mode does, and cases
marked ``ambiguous`` are only required to be declined.

    uv run python -m engine.agents.triage_eval
    uv run python -m engine.agents.triage_eval --split holdout --min-accuracy 0.9
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from engine.agents.teams_types import Complexity, TriageDecision
from engine.agents.triage import classify_rules

GOLDEN_FILE = Path(__file__).with_name("triage_golden.json")
SPLITS = ("dev", "holdout")

Classifier = Callable[[str, list[str]], TriageDecision | None]


@dataclass(frozen=True)
class GoldenCase:
    request: str
    complexity: Complexity
    split: str
    test_only: bool = False
    ambiguous: bool = False
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    decided: bool  # False when the rules abstained and the model would be asked
    complexity: Complexity  # the rules' answer, or Standard when they abstained
    test_only: bool

    @property
    def correct(self) -> bool:
        return self.complexity == self.case.complexity and self.test_only == self.case.test_only


@dataclass
class EvalReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def scored(self) -> list[CaseResult]:
        return [r for r in self.results if not r.case.ambiguous]

    @property
    def accuracy(self) -> float:
        scored = self.scored
        return sum(r.correct for r in scored) / len(scored) if scored else 0.0

    @property
    def failures(self) -> list[CaseResult]:
        return [r for r in self.scored if not r.correct]

    @property
    def ambiguous_not_declined(self) -> list[CaseResult]:
        return [r for r in self.results if r.case.ambiguous and r.decided]

    @property
    def false_test_only(self) -> list[CaseResult]:
        """Report-only is the one label that removes editing, so it must never be wrong."""
        return [r for r in self.results if r.test_only and not r.case.test_only]

    @property
    def under_triaged(self) -> list[CaseResult]:
        return [
            r
            for r in self.scored
            if r.case.complexity == Complexity.COMPLEX and r.complexity == Complexity.QUICK
        ]

    @property
    def decline_rate(self) -> float:
        return sum(not r.decided for r in self.results) / len(self.results) if self.results else 0

    def recall(self) -> dict[Complexity, tuple[int, int]]:
        totals: Counter[Complexity] = Counter()
        hits: Counter[Complexity] = Counter()
        for r in self.scored:
            totals[r.case.complexity] += 1
            hits[r.case.complexity] += r.correct
        return {c: (hits[c], totals[c]) for c in Complexity}

    def passes(self, min_accuracy: float) -> bool:
        return (
            self.accuracy >= min_accuracy
            and not self.ambiguous_not_declined
            and not self.false_test_only
            and not self.under_triaged
        )


def load_cases(split: str | None = None, path: Path = GOLDEN_FILE) -> list[GoldenCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        GoldenCase(
            request=item["request"],
            complexity=Complexity(item["complexity"]),
            split=item["split"],
            test_only=bool(item.get("test_only", False)),
            ambiguous=bool(item.get("ambiguous", False)),
            paths=tuple(item.get("paths", ())),
        )
        for item in raw
    ]
    unknown = {c.split for c in cases} - set(SPLITS)
    if unknown:
        raise ValueError(f"unknown split(s) in golden file: {sorted(unknown)}")
    return [c for c in cases if split in (None, "all", c.split)]


def evaluate(cases: Sequence[GoldenCase], classify: Classifier = classify_rules) -> EvalReport:
    report = EvalReport()
    for case in cases:
        decision = classify(case.request, list(case.paths))
        report.results.append(
            CaseResult(
                case=case,
                decided=decision is not None,
                complexity=decision.complexity if decision else Complexity.STANDARD,
                test_only=decision.test_only if decision else False,
            )
        )
    return report


def _label(complexity: Complexity, test_only: bool) -> str:
    return f"{complexity.value}{' (test-only)' if test_only else ''}"


def format_report(report: EvalReport, *, show_failures: bool = True) -> str:
    lines = [
        f"cases: {len(report.results)} "
        f"({len(report.scored)} scored, {len(report.results) - len(report.scored)} ambiguous)",
        f"accuracy: {report.accuracy:.1%} ({len(report.scored) - len(report.failures)}"
        f"/{len(report.scored)})",
    ]
    for complexity, (hit, total) in report.recall().items():
        lines.append(f"  {complexity.value:<9} {hit}/{total}")
    lines.append(f"rules declined (cheap model would decide): {report.decline_rate:.1%}")
    lines.append(f"ambiguous cases wrongly decided by rules: {len(report.ambiguous_not_declined)}")
    lines.append(f"test-only false positives: {len(report.false_test_only)}")
    lines.append(f"complex requests labelled quick: {len(report.under_triaged)}")
    if show_failures:
        for r in report.failures:
            lines.append(
                f"MISS [{r.case.split}] {r.case.request!r} "
                f"expected {_label(r.case.complexity, r.case.test_only)}, "
                f"got {_label(r.complexity, r.test_only)}{'' if r.decided else ' (declined)'}"
            )
        for r in report.ambiguous_not_declined:
            lines.append(f"DECIDED [{r.case.split}] ambiguous case {r.case.request!r}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the triage rules on the golden requests")
    parser.add_argument("--split", choices=("all", *SPLITS), default="all")
    parser.add_argument("--min-accuracy", type=float, default=0.9)
    parser.add_argument("--quiet", action="store_true", help="omit the list of misses")
    args = parser.parse_args(argv)
    report = evaluate(load_cases(args.split))
    print(format_report(report, show_failures=not args.quiet))
    ok = report.passes(args.min_accuracy)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
