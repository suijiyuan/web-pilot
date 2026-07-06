from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .errors import PlanError
from .plan import load_plan
from .runner import RunOptions, run_plan


def _parse_vars(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise PlanError(f"invalid --var '{raw}', expected KEY=VALUE")
        k, v = raw.split("=", 1)
        k = k.strip()
        if not k:
            raise PlanError(f"invalid --var '{raw}', empty key")
        out[k] = v
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="web-pilot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run test plan")
    run_p.add_argument("--plan", required=True, help="path to plan json")
    run_p.add_argument("--base-url", default=None, help="used when step.url starts with '/'")
    run_p.add_argument("--headed", action="store_true", help="force headed mode")
    run_p.add_argument("--headless", action="store_true", help="force headless mode")
    run_p.add_argument("--channel", default=None, help="chrome | msedge | chromium | ...")
    run_p.add_argument("--trace", action="store_true", help="save trace.zip per test")
    run_p.add_argument("--timeout-ms", type=int, default=30_000)
    run_p.add_argument("--only", action="append", default=[], help="only run a test name (repeatable)")
    run_p.add_argument("--var", action="append", default=[], help="variables for plan interpolation, KEY=VALUE (repeatable)")

    list_p = sub.add_parser("list", help="list tests in plan")
    list_p.add_argument("--plan", required=True, help="path to plan json")
    list_p.add_argument("--var", action="append", default=[], help="variables for plan interpolation, KEY=VALUE (repeatable)")

    return parser


def _print_results(results) -> None:
    passed = 0
    failed = 0
    for r in results:
        if r.passed:
            passed += 1
            sys.stdout.write(f"PASS  {r.name}  ({r.duration_ms}ms)  {r.artifacts_dir}\n")
        else:
            failed += 1
            sys.stdout.write(f"FAIL  {r.name}  ({r.duration_ms}ms)  {r.artifacts_dir}\n")
            if r.error:
                sys.stdout.write(f"  {r.error}\n")
    sys.stdout.write(f"\nSummary: {passed} passed, {failed} failed\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        extra_vars = _parse_vars(args.var)
        plan = load_plan(Path(args.plan), extra_vars=extra_vars)

        if args.cmd == "list":
            for t in plan.tests:
                sys.stdout.write(f"{t.name}\n")
            return 0

        headed_opt = None
        if args.headed and args.headless:
            raise PlanError("cannot set both --headed and --headless")
        if args.headed:
            headed_opt = True
        if args.headless:
            headed_opt = False

        only = set(args.only) if args.only else None
        if only is not None:
            available_tests = {test.name for test in plan.tests}
            unknown_tests = sorted(only - available_tests)
            if unknown_tests:
                raise PlanError(
                    "unknown test name(s) in --only: " + ", ".join(unknown_tests)
                )
        results = run_plan(
            plan,
            options=RunOptions(
                base_url=args.base_url,
                headed=headed_opt,
                channel=args.channel,
                trace=bool(args.trace),
                timeout_ms=int(args.timeout_ms),
            ),
            only_tests=only,
        )
        _print_results(results)
        return 0 if all(r.passed for r in results) else 1
    except PlanError as e:
        sys.stderr.write(f"PlanError: {e}\n")
        return 2


__all__ = ["main"]
