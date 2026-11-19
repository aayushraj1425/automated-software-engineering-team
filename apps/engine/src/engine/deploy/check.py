"""Runnable dry-run: would the preview adapter accept this chart?

    uv run python -m engine.deploy.check --chart ../../infra/helm/asep-preview-fixture

Never contacts a cluster and needs no credentials. With Helm installed it also
renders the chart and applies the manifest policy; without it, it says so.
Exit code 0 means accepted, 1 rejected.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from engine.deploy.contracts import PreviewOptions
from engine.deploy.preview import check_chart


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run the preview chart checks.")
    parser.add_argument("--chart", required=True, help="chart folder")
    parser.add_argument("--values", help="optional values file, relative to --root")
    parser.add_argument("--root", help="folder that contains the chart (default: its parent)")
    parser.add_argument("--no-render", action="store_true", help="skip the helm template step")
    args = parser.parse_args(argv)

    chart = Path(args.chart).resolve()
    root = Path(args.root).resolve() if args.root else chart.parent
    try:
        relative = chart.relative_to(root).as_posix()
    except ValueError:
        print("the chart must be inside --root", file=sys.stderr)
        return 1
    options = PreviewOptions(chart_path=relative, values_file=args.values)
    report = asyncio.run(check_chart(root, options, render=not args.no_render))
    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
