"""Command-line interface for the bounded FM20 visibility capture harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tools.fm20_linux_probe import ProbeError
from tools.fm20_linux_probe_runtime import choose_pid
from tools.fm20_visibility_capture import CaptureError, capture
from tools.fm20_visibility_trace import ATTRIBUTE_OFFSETS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture manager-visible FM20 attribute render events"
    )
    parser.add_argument("--pid", type=int, help="FM20 host PID; auto-detected")
    parser.add_argument(
        "--duration", type=float, default=30.0,
        help="seconds to collect after GDB is attached (default: 30)",
    )
    parser.add_argument(
        "--attribute", action="append", choices=tuple(sorted(ATTRIBUTE_OFFSETS)),
        help="attribute to capture; repeatable; defaults to the supported set",
    )
    parser.add_argument(
        "--player-id", action="append", type=int, default=[],
        help="optional player filter; repeatable",
    )
    parser.add_argument("--output", type=Path, help="write final JSON to this path")
    parser.add_argument(
        "--diagnostic-hits", action="store_true",
        help="count hook executions and attribute IDs without reading extra values",
    )
    parser.add_argument(
        "--trace-knowledge-cache", action="store_true",
        help="trace manager-knowledge lookup results without raw attributes",
    )
    parser.add_argument(
        "--trace-knowledge-decision", action="store_true",
        help="trace FM's explicit, baseline, and combined knowledge levels",
    )
    parser.add_argument(
        "--replay-same-cell", action="store_true",
        help="research-only: directly rebuild one rendered cell and compare it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = capture(
            choose_pid(args.pid),
            duration_seconds=args.duration,
            attributes=args.attribute or tuple(sorted(ATTRIBUTE_OFFSETS)),
            player_ids=args.player_id,
            diagnostic_hits=args.diagnostic_hits,
            trace_knowledge_cache=args.trace_knowledge_cache,
            trace_knowledge_decision=args.trace_knowledge_decision,
            replay_same_cell=args.replay_same_cell,
            ready_callback=lambda: print(
                "Capture armed; redraw the target FM table now.",
                file=sys.stderr,
                flush=True,
            ),
        )
    except (CaptureError, ProbeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result.to_dict(), indent=2)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0
