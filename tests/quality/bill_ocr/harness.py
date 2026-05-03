"""Test harness for bill_ocr prompt evaluation.

Loads YAML cases, calls OpenRouter with a system prompt × model,
parses output via the production `parse_ai_response`, scores it.

Run via tests/quality/bill_ocr/run.py — do not import in pytest.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Load .env first (mirrors tests/quality/bench.py).
_ROOT = Path(__file__).resolve().parents[3]
_env_path = _ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k == "DOWNLOAD_PROXY":
            continue
        os.environ.setdefault(_k, _v)

import yaml  # noqa: E402

from steward.features.bills.parse import parse_ai_response  # noqa: E402
from steward.helpers.ai import make_openrouter_query  # noqa: E402

CASES_PATH = Path(__file__).parent / "cases.yaml"
PROMPTS_DIR = Path(__file__).parent / "prompts"
RESULTS_DIR = Path(__file__).parent / "results"
RAW_DIR = RESULTS_DIR / "raw"

DEFAULT_MODELS = [
    "google/gemini-2.5-flash",
    "google/gemini-2.5-pro",
    "x-ai/grok-4-fast",
]

MAX_TOKENS = 2048
TIMEOUT_S = 60.0
DEFAULT_BUDGET = 200

# Tolerance when comparing per-person totals (minor units).
# Models often round 16.67 to 16.66 or similar — allow 2 kopecks slack
# but tighten to within 1% of the larger of expected or actual.
PER_PERSON_TOLERANCE_MINOR = 5
PER_PERSON_TOLERANCE_RATIO = 0.02


# ---------- Case loading ----------

@dataclass
class Person:
    name: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExpectedItem:
    name_contains: str
    creditor: str | None = None
    per_person_minor: dict[str, int] | None = None
    unit_price_minor: int | None = None
    quantity: int | None = None
    debtors: list[str] | None = None
    unit_price_minor_options: list[int] | None = None
    new_persons_contains: list[str] | None = None


@dataclass
class Case:
    id: str
    description: str
    speaker: str | None
    persons: list[Person]
    context: str
    currency: str
    items: list[ExpectedItem]
    no_items: bool = False
    expected_questions: bool | None = None
    tags: list[str] = field(default_factory=list)


def _parse_persons(raw: list) -> list[Person]:
    persons = []
    for entry in raw:
        if isinstance(entry, str):
            persons.append(Person(name=entry))
        else:
            persons.append(Person(name=entry["name"], aliases=entry.get("aliases", [])))
    return persons


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = []
    for c in raw:
        exp = c.get("expected", {})
        items_raw = exp.get("items", [])
        items = []
        for it in items_raw:
            items.append(ExpectedItem(
                name_contains=it["name_contains"],
                creditor=it.get("creditor"),
                per_person_minor=it.get("per_person_minor"),
                unit_price_minor=(it.get("strict") or {}).get("unit_price_minor"),
                quantity=(it.get("strict") or {}).get("quantity"),
                debtors=(it.get("strict") or {}).get("debtors"),
                unit_price_minor_options=it.get("unit_price_minor_options"),
                new_persons_contains=it.get("new_persons_contains"),
            ))
        cases.append(Case(
            id=c["id"],
            description=c.get("description", ""),
            speaker=c.get("speaker"),
            persons=_parse_persons(c.get("persons", [])),
            context=c["context"],
            currency=exp.get("currency", "BYN"),
            items=items,
            no_items=exp.get("no_items", False),
            expected_questions=exp.get("expected_questions"),
            tags=c.get("tags", []),
        ))
    return cases


# ---------- Prompt input formatting (mirrors production) ----------

def _build_persons_block(persons: list[Person]) -> str:
    """Mirrors steward.features.bills.parse.build_persons_directory format."""
    lines = ["[СПРАВОЧНИК ЛЮДЕЙ]"]
    for p in persons:
        if p.aliases:
            lines.append(f"{p.name} ({', '.join(p.aliases)})")
        else:
            lines.append(p.name)
    return "\n".join(lines)


def build_user_prompt(case: Case) -> str:
    persons_block = _build_persons_block(case.persons)
    ctx = case.context
    if case.speaker:
        ctx = f"Я = {case.speaker}\n\n{ctx}"
    return f"{persons_block}\n\n---\n\n{ctx}"


# ---------- Model calling with cache ----------

def _cache_path(case_id: str, prompt_name: str, model: str) -> Path:
    safe_model = model.replace("/", "__")
    return RAW_DIR / f"{case_id}__{prompt_name}__{safe_model}.txt"


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


async def call_model(
    case: Case,
    prompt_name: str,
    prompt_text: str,
    model: str,
    *,
    no_cache: bool = False,
    max_retries: int = 5,
) -> tuple[str, float, bool]:
    """Returns (response_text, latency_seconds, cache_hit)."""
    cp = _cache_path(case.id, prompt_name, model)
    if not no_cache and cp.exists():
        return cp.read_text(encoding="utf-8"), 0.0, True

    user_prompt = build_user_prompt(case)
    t0 = time.perf_counter()

    last_exc: Exception | None = None
    delay = 3.0
    for attempt in range(max_retries):
        try:
            text = await make_openrouter_query(
                # Shared user id ensures the per-user 7/20s bucket
                # is the global throttle for the whole eval run.
                user_id="bill_ocr_eval",
                model=model,
                messages=[("user", user_prompt)],
                system_prompt=prompt_text,
                max_tokens=MAX_TOKENS,
                timeout_seconds=TIMEOUT_S,
            )
            break
        except Exception as e:
            last_exc = e
            name = type(e).__name__
            # Retry on rate-limit + transient errors. Otherwise bail.
            if "BucketFull" in name or "RateLimit" in name or "timeout" in str(e).lower():
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 30.0)
                continue
            raise
    else:
        assert last_exc is not None
        raise last_exc

    latency = time.perf_counter() - t0
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(text, encoding="utf-8")
    return text, latency, False


# ---------- Scoring ----------

@dataclass
class CaseScore:
    case_id: str
    model: str
    prompt: str
    score: float
    breakdown: dict
    cache_hit: bool
    latency: float
    error: str | None = None


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _name_to_minor(rows: list[dict], name_to_keys: dict[str, set[str]]) -> dict[str, int]:
    """Compute per-person debt totals from parsed rows.

    name_to_keys: canonical name -> set of normalized aliases (incl. itself).
    Unknown debtors and "-" are skipped.
    """
    totals: dict[str, int] = {}
    for row in rows:
        debtors_raw = (row["debtors_raw"] or "").strip()
        if not debtors_raw or debtors_raw == "-":
            continue
        debtor_names = [d.strip() for d in debtors_raw.split(",") if d.strip()]
        if not debtor_names:
            continue
        total_minor = row["price_minor"] * row["quantity"]
        per_debtor = total_minor // len(debtor_names)
        for dn in debtor_names:
            key = _norm(dn)
            matched = None
            for canonical, aliases in name_to_keys.items():
                if key in aliases:
                    matched = canonical
                    break
            if matched is None:
                matched = dn  # unknown — keep as-is, will fail comparison
            totals[matched] = totals.get(matched, 0) + per_debtor
    return totals


def _build_alias_map(case: Case) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in case.persons:
        keys = {_norm(p.name)} | {_norm(a) for a in p.aliases}
        out[p.name] = keys
    return out


def _close_enough(actual: int, expected: int) -> bool:
    if abs(actual - expected) <= PER_PERSON_TOLERANCE_MINOR:
        return True
    base = max(abs(actual), abs(expected), 1)
    return abs(actual - expected) / base <= PER_PERSON_TOLERANCE_RATIO


def score_case(
    case: Case,
    response_text: str,
) -> tuple[float, dict]:
    """Returns (score in [0,1], breakdown dict)."""
    breakdown: dict = {
        "currency_ok": False,
        "items_count_ok": False,
        "items_matched": 0,
        "items_expected": len(case.items),
        "per_person_score": 0.0,
        "per_person_detail": {},
        "creditor_score": 0.0,
        "questions_ok": True,
        "spurious_penalty": 0.0,
        "errors": [],
    }

    try:
        currency, rows, new_persons, questions = parse_ai_response(response_text)
    except Exception as e:
        breakdown["errors"].append(f"parse_failed: {e}")
        return 0.0, breakdown

    breakdown["parsed"] = {
        "currency": currency,
        "rows": rows,
        "new_persons": new_persons,
        "questions": questions,
    }

    # 1. Currency (10%)
    breakdown["currency_ok"] = currency.upper() == case.currency.upper()

    # 5. Questions (binary, weight 5%)
    if case.expected_questions is True:
        breakdown["questions_ok"] = bool(questions)
    elif case.expected_questions is False:
        # No requirement — allow either. Don't penalize if questions present.
        breakdown["questions_ok"] = True
    # If None: pass.

    # No-items shortcut — case expects ZERO rows, just questions/currency.
    if case.no_items:
        breakdown["items_count_ok"] = len(rows) == 0
        currency_pt = 0.20 if breakdown["currency_ok"] else 0.0
        items_pt = 0.40 if breakdown["items_count_ok"] else 0.0
        questions_pt = 0.40 if breakdown["questions_ok"] else 0.0
        # spurious if rows not empty
        if rows:
            breakdown["spurious_penalty"] = 0.10 * len(rows)
        score = max(0.0, currency_pt + items_pt + questions_pt - breakdown["spurious_penalty"])
        return min(1.0, score), breakdown

    # 2. Items count + name match (30%)
    # match each expected item to a row by name fuzzy
    matched_rows = set()
    expected_items_matched = 0

    # Group rows by item name signature (treat same group_id rows as the same item).
    # For per-person scoring this doesn't matter, but for "did model produce the item"
    # we just check substring on row names.
    for exp in case.items:
        needle = _norm(exp.name_contains)
        for i, row in enumerate(rows):
            if i in matched_rows:
                continue
            if needle in _norm(row["name"]):
                matched_rows.add(i)
                expected_items_matched += 1
                break

    breakdown["items_matched"] = expected_items_matched
    items_match_score = expected_items_matched / max(len(case.items), 1)
    breakdown["items_count_ok"] = expected_items_matched == len(case.items)

    # Items count penalty: distinct item names in rows vs expected count.
    # Group by (group_id or stem-name) to count distinct items.
    # Strip "(1/4)", "(3/8)", trailing decimals etc. used by models to
    # disambiguate fractional shares — they're the same physical item.
    import re as _re
    _frac_suffix = _re.compile(r"\s*\([^)]*\)\s*$")

    def _stem(name: str) -> str:
        return _frac_suffix.sub("", name).strip().casefold()

    # Distinct count: bucket rows by stem-name, multiple GroupIds with the
    # same stem still count as one "type" of item (since the case probably
    # described "2 hookahs" as one logical item with 2 assignments).
    distinct_stems: set[str] = set()
    for row in rows:
        distinct_stems.add(_stem(row["name"]))
    expected_count = len(case.items)
    spurious = max(0, len(distinct_stems) - expected_count)
    breakdown["spurious_penalty"] = 0.05 * spurious
    breakdown["distinct_items"] = len(distinct_stems)

    # 3. Quantitative correctness (per_person_minor mode) (40%)
    alias_map = _build_alias_map(case)
    actual_per_person = _name_to_minor(rows, alias_map)
    breakdown["per_person_actual"] = actual_per_person

    per_person_target = {}
    for exp in case.items:
        if exp.per_person_minor:
            for n, v in exp.per_person_minor.items():
                per_person_target[n] = per_person_target.get(n, 0) + v
    breakdown["per_person_expected"] = per_person_target

    if per_person_target:
        ok = 0
        details = {}
        for name, expected_v in per_person_target.items():
            actual_v = actual_per_person.get(name, 0)
            close = _close_enough(actual_v, expected_v)
            details[name] = {"expected": expected_v, "actual": actual_v, "ok": close}
            if close:
                ok += 1
        breakdown["per_person_score"] = ok / len(per_person_target)
        breakdown["per_person_detail"] = details
    else:
        # Strict mode fallback: just check unit_price_minor_options if provided
        # (e.g. ambiguous case where any of [1000, 3000] is ok)
        if any(exp.unit_price_minor_options for exp in case.items):
            hits = 0
            for exp in case.items:
                if exp.unit_price_minor_options:
                    for row in rows:
                        if _norm(exp.name_contains) in _norm(row["name"]):
                            if row["price_minor"] in exp.unit_price_minor_options:
                                hits += 1
                            break
            breakdown["per_person_score"] = hits / len(case.items)
        else:
            breakdown["per_person_score"] = items_match_score

    # 4. Creditor match (10%)
    creditor_hits = 0
    creditor_total = 0
    for exp in case.items:
        if exp.creditor is None:
            continue
        creditor_total += 1
        for row in rows:
            if _norm(exp.name_contains) in _norm(row["name"]):
                cred_actual = (row["creditor_raw"] or "").strip()
                if exp.creditor == "-":
                    if cred_actual == "-" or not cred_actual:
                        creditor_hits += 1
                else:
                    if _norm(cred_actual) in alias_map.get(exp.creditor, {_norm(exp.creditor)}):
                        creditor_hits += 1
                break
    if creditor_total:
        breakdown["creditor_score"] = creditor_hits / creditor_total
    else:
        breakdown["creditor_score"] = 1.0

    # New persons check
    np_score = 1.0
    np_details = []
    for exp in case.items:
        if exp.new_persons_contains:
            for needle in exp.new_persons_contains:
                hit = any(_norm(needle) in _norm(np) for np in new_persons)
                np_details.append({"needle": needle, "ok": hit})
                if not hit:
                    np_score *= 0.5
    breakdown["new_persons_score"] = np_score
    breakdown["new_persons_detail"] = np_details

    # Final weighted score
    currency_pt = 0.10 if breakdown["currency_ok"] else 0.0
    items_pt = 0.20 * items_match_score
    quantitative_pt = 0.40 * breakdown["per_person_score"]
    creditor_pt = 0.15 * breakdown["creditor_score"]
    questions_pt = 0.05 if breakdown["questions_ok"] else 0.0
    new_persons_pt = 0.10 * np_score

    raw_score = (
        currency_pt + items_pt + quantitative_pt + creditor_pt + questions_pt + new_persons_pt
    )
    score = max(0.0, raw_score - breakdown["spurious_penalty"])
    return min(1.0, score), breakdown


# ---------- Runner ----------

async def run_eval(
    cases: list[Case],
    models: list[str],
    prompt_names: list[str],
    *,
    no_cache: bool = False,
    max_calls: int = DEFAULT_BUDGET,
    on_progress=None,
) -> list[CaseScore]:
    # Production limits: 7 calls / 20s per user, 20 calls / min total.
    # Use low concurrency + retry-on-bucket-full in call_model.
    sem = asyncio.Semaphore(2)
    results: list[CaseScore] = []
    calls_made = 0
    calls_skipped_budget = 0

    prompts = {p: load_prompt(p) for p in prompt_names}

    async def _one(case: Case, prompt_name: str, model: str):
        nonlocal calls_made, calls_skipped_budget
        async with sem:
            cp = _cache_path(case.id, prompt_name, model)
            cache_hit_pre = cp.exists() and not no_cache
            if not cache_hit_pre and calls_made >= max_calls:
                calls_skipped_budget += 1
                return CaseScore(
                    case_id=case.id, model=model, prompt=prompt_name,
                    score=0.0, breakdown={}, cache_hit=False, latency=0.0,
                    error="budget_exceeded",
                )
            try:
                text, latency, cache_hit = await call_model(
                    case, prompt_name, prompts[prompt_name], model, no_cache=no_cache,
                )
                if not cache_hit:
                    calls_made += 1
            except Exception as e:
                return CaseScore(
                    case_id=case.id, model=model, prompt=prompt_name,
                    score=0.0, breakdown={}, cache_hit=False, latency=0.0,
                    error=f"{type(e).__name__}: {e}",
                )
            score, breakdown = score_case(case, text)
            cs = CaseScore(
                case_id=case.id, model=model, prompt=prompt_name,
                score=score, breakdown=breakdown,
                cache_hit=cache_hit, latency=latency,
            )
            if on_progress:
                on_progress(cs)
            return cs

    tasks = [
        _one(case, prompt_name, model)
        for prompt_name in prompt_names
        for model in models
        for case in cases
    ]
    results = await asyncio.gather(*tasks)
    return results


# ---------- Reporting ----------

def write_report(
    results: list[CaseScore],
    cases: list[Case],
    out_path: Path,
    *,
    title: str = "Bill OCR Eval",
) -> None:
    by_id = {c.id: c for c in cases}
    # group: (prompt, model) -> list of CaseScore
    groups: dict[tuple[str, str], list[CaseScore]] = {}
    for r in results:
        groups.setdefault((r.prompt, r.model), []).append(r)

    lines = [f"# {title}\n"]
    lines.append(f"Cases: {len(cases)}  Models: {len(set(r.model for r in results))}  "
                 f"Prompt variants: {len(set(r.prompt for r in results))}\n")

    # Summary table
    lines.append("## Summary (avg score per prompt × model)\n")
    prompts = sorted({r.prompt for r in results})
    models = sorted({r.model for r in results})
    header = "| prompt \\ model | " + " | ".join(models) + " | avg |"
    sep = "|---|" + "|".join(["---"] * (len(models) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for p in prompts:
        row = [p]
        per_model = []
        for m in models:
            xs = [r.score for r in groups.get((p, m), []) if r.error is None]
            avg = sum(xs) / len(xs) if xs else 0.0
            per_model.append(avg)
            row.append(f"{avg:.3f}")
        avg_overall = sum(per_model) / len(per_model) if per_model else 0.0
        row.append(f"**{avg_overall:.3f}**")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Per-case grid
    lines.append("## Per-case scores\n")
    for p in prompts:
        lines.append(f"### Prompt: `{p}`\n")
        header = "| case | " + " | ".join(models) + " |"
        sep = "|---|" + "|".join(["---"] * len(models)) + "|"
        lines.append(header)
        lines.append(sep)
        for c in cases:
            row = [c.id]
            for m in models:
                cs_list = [x for x in groups.get((p, m), []) if x.case_id == c.id]
                if not cs_list:
                    row.append("-")
                    continue
                cs = cs_list[0]
                if cs.error:
                    row.append(f"ERR")
                else:
                    flag = "" if cs.score >= 0.85 else (" ⚠" if cs.score >= 0.5 else " ✗")
                    row.append(f"{cs.score:.2f}{flag}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # Failure detail
    lines.append("## Failure detail (score < 0.7)\n")
    for r in results:
        if r.error or r.score < 0.7:
            c = by_id.get(r.case_id)
            lines.append(f"### `{r.case_id}` × `{r.prompt}` × `{r.model}` — score {r.score:.2f}\n")
            if c:
                lines.append(f"_{c.description}_\n")
            if r.error:
                lines.append(f"**ERROR:** {r.error}\n")
                continue
            bd = r.breakdown
            if bd:
                lines.append(f"- currency_ok={bd.get('currency_ok')} "
                             f"items {bd.get('items_matched')}/{bd.get('items_expected')} "
                             f"per_person={bd.get('per_person_score', 0):.2f} "
                             f"creditor={bd.get('creditor_score', 0):.2f} "
                             f"questions_ok={bd.get('questions_ok')}")
                if bd.get("per_person_expected"):
                    lines.append(f"- expected per-person: `{bd['per_person_expected']}`")
                    lines.append(f"- actual per-person:   `{bd.get('per_person_actual', {})}`")
                if bd.get("errors"):
                    lines.append(f"- errors: {bd['errors']}")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def aggregate(results: list[CaseScore]) -> dict[tuple[str, str], float]:
    groups: dict[tuple[str, str], list[float]] = {}
    for r in results:
        if r.error is None:
            groups.setdefault((r.prompt, r.model), []).append(r.score)
    return {k: (sum(v) / len(v) if v else 0.0) for k, v in groups.items()}
