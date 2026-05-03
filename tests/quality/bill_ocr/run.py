"""CLI for the bill_ocr eval harness.

Usage:
    ./venv/bin/python -m tests.quality.bill_ocr.run \
        [--models google/gemini-2.5-flash,google/gemini-2.5-pro,x-ai/grok-4-fast] \
        [--prompts baseline,v2_fractions] \
        [--cases simple_pizza,hookah_quarter] \
        [--no-cache] \
        [--max-calls 200] \
        [--out results/2026-05-02_baseline.md]
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import sys
from pathlib import Path

from tests.quality.bill_ocr.harness import (  # type: ignore
    DEFAULT_BUDGET,
    DEFAULT_MODELS,
    PROMPTS_DIR,
    RESULTS_DIR,
    aggregate,
    load_cases,
    run_eval,
    write_report,
)


def _parse_csv(arg: str | None) -> list[str] | None:
    if not arg:
        return None
    return [s.strip() for s in arg.split(",") if s.strip()]


def main():
    parser = argparse.ArgumentParser(description="Bill OCR prompt eval harness")
    parser.add_argument("--models", help="comma-separated model ids")
    parser.add_argument("--prompts", default="baseline",
                        help="comma-separated prompt names from prompts/")
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--no-cache", action="store_true",
                        help="bypass raw output cache")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_BUDGET,
                        help=f"max model calls (default {DEFAULT_BUDGET})")
    parser.add_argument("--out", help="report path (default: results/<timestamp>.md)")
    parser.add_argument("--title", default="Bill OCR Eval")
    args = parser.parse_args()

    models = _parse_csv(args.models) or DEFAULT_MODELS
    prompts = _parse_csv(args.prompts) or ["baseline"]
    case_filter = _parse_csv(args.cases)

    # Validate prompts exist.
    for p in prompts:
        if not (PROMPTS_DIR / f"{p}.txt").exists():
            print(f"ERROR: prompt not found: {p} (expected at {PROMPTS_DIR / (p + '.txt')})",
                  file=sys.stderr)
            sys.exit(2)

    cases = load_cases()
    if case_filter:
        ids = set(case_filter)
        cases = [c for c in cases if c.id in ids]
        missing = ids - {c.id for c in cases}
        if missing:
            print(f"WARNING: case ids not found: {missing}", file=sys.stderr)

    if not cases:
        print("ERROR: no cases to run", file=sys.stderr)
        sys.exit(2)

    print(f"Running {len(cases)} cases × {len(models)} models × {len(prompts)} prompts "
          f"= {len(cases) * len(models) * len(prompts)} total calls "
          f"(cache {'BYPASSED' if args.no_cache else 'enabled'}, budget={args.max_calls})")

    seen = 0
    total = len(cases) * len(models) * len(prompts)
    def _on_progress(cs):
        nonlocal seen
        seen += 1
        flag = "ERR" if cs.error else f"{cs.score:.2f}"
        cache = "C" if cs.cache_hit else " "
        print(f"  [{seen:3d}/{total}] {cache} {cs.prompt:24s} {cs.model:30s} "
              f"{cs.case_id:25s} -> {flag}")

    results = asyncio.run(run_eval(
        cases, models, prompts,
        no_cache=args.no_cache,
        max_calls=args.max_calls,
        on_progress=_on_progress,
    ))

    out_path = Path(args.out) if args.out else (
        RESULTS_DIR / f"{_dt.datetime.now().strftime('%Y-%m-%d_%H%M%S')}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(results, cases, out_path, title=args.title)
    print(f"\nWrote {out_path}")

    print("\nAggregate scores:")
    agg = aggregate(results)
    for (prompt, model), avg in sorted(agg.items()):
        print(f"  {prompt:24s} {model:35s} avg={avg:.3f}")

    n_errors = sum(1 for r in results if r.error)
    if n_errors:
        print(f"\n{n_errors} call(s) errored — see report.")


if __name__ == "__main__":
    main()
