# Bill OCR Eval Harness

Benchmark + iterative-improvement loop for `prompts/bill_ocr.txt`.

## Run

```bash
# Quick smoke (one case, one model):
./venv/bin/python -m tests.quality.bill_ocr.run \
  --models google/gemini-2.5-flash \
  --prompts baseline \
  --cases simple_pizza

# Full run on all 3 models, baseline + v2:
./venv/bin/python -m tests.quality.bill_ocr.run \
  --models google/gemini-2.5-flash,google/gemini-2.5-pro,x-ai/grok-4-fast \
  --prompts baseline,v2_integer_qty \
  --out tests/quality/bill_ocr/results/run.md
```

### Flags

| flag | default | what it does |
|---|---|---|
| `--models` | `gemini-2.5-flash,gemini-2.5-pro,grok-4-fast` (CSV) | OpenRouter model ids |
| `--prompts` | `baseline` | Prompt names from `prompts/` (without `.txt`) |
| `--cases` | (all) | Comma-separated case ids to filter |
| `--no-cache` | off | Bypass the `results/raw/` cache and re-call models |
| `--max-calls` | 200 | Max non-cached model calls per run (cap for budget) |
| `--out` | `results/<timestamp>.md` | Where to write the report |
| `--title` | `"Bill OCR Eval"` | Title in report header |

## What it does

1. Loads `cases.yaml` — currently 16 hand-authored cases covering simple
   splits, fractional consumption, multi-creditor scenes, currency
   variants, OCR-style receipts, "missing amount" → question, etc.
2. For each (case × prompt × model), formats the input the same way
   production does (via `[СПРАВОЧНИК ЛЮДЕЙ]` + `Я = <speaker>` prefix +
   raw context), calls OpenRouter with `max_tokens=2048`, `timeout=60s`.
3. Caches raw model output in `results/raw/<case>__<prompt>__<model>.txt`
   so re-runs are free.
4. Parses the output through the production
   `steward.features.bills.parse.parse_ai_response` (no reinvention).
5. Scores each case on a 0..1 rubric:
   - 10 % currency match (`BYN` / `RUB` / `USD` / `EUR`)
   - 20 % items extracted (substring match of `name_contains`)
   - 40 % quantitative correctness via per-person debt totals
     (computed from `unit_price × quantity / len(debtors)`, summed
     per debtor)
   - 15 % creditor match
   - 10 % expected new persons appear in `[ДАННЫЕ]`
   - 5 % `[ВОПРОСЫ]` present when `expected_questions: true`
   - minus 5 % per spurious item (distinct stem-name not in expected)

   For a `no_items: true` case (e.g. "I tipped but didn't say how
   much"): currency 20 %, no rows 40 %, questions 40 %.
6. Writes a markdown report with summary table, per-case grid, and
   detailed breakdown for any case below 0.70.

## Adding a new case

Append to `cases.yaml`:

```yaml
- id: my_case
  description: short note
  speaker: Кирилл                  # optional, prepended as "Я = Кирилл"
  persons:
    - {name: Кирилл}
    - {name: Дима, aliases: [Димон]}
  context: |
    multi-line text describing the situation
  expected:
    currency: BYN
    items:
      - name_contains: пицц       # substring (case-insensitive)
        creditor: Кирилл           # or "-" for unknown
        per_person_minor:          # final debt totals per person, in minor units
          Кирилл: 1500             # 15.00 BYN
          Дима: 1500
  tags: [my_tag]
```

Special expected keys:
- `expected_questions: true` — `[ВОПРОСЫ]` must be non-empty.
- `no_items: true` — case should produce zero rows (e.g. amount missing).
- `unit_price_minor_options: [1000, 3000]` — accept any of these for
  ambiguous cases where multiple encodings work.
- `new_persons_contains: [Серёж]` — these substrings should appear in
  the `[ДАННЫЕ]` block.

## Adding a prompt variant

Drop a new file in `prompts/` (e.g. `v3_my_idea.txt`), then run with
`--prompts baseline,v3_my_idea`. The harness loads each prompt by
filename stem.

## Files

- `cases.yaml` — test corpus (edit this to add cases).
- `harness.py` — case loader, model caller (cached), scorer, report writer.
- `run.py` — CLI entry point.
- `prompts/baseline.txt` — snapshot of `prompts/bill_ocr.txt` at start.
- `prompts/v2_integer_qty.txt` — current best prompt (see `results/FINAL.md`).
- `prompts/v3_compact.txt` — half-length variant (worse than v2 — kept
  for reference).
- `results/FINAL.md` — final report with per-model deltas.
- `results/raw/` — cached model outputs.

## Constraints

- Only OpenRouter is wired up — no Yandex / NVIDIA fallback.
- The harness shares one OpenRouter user_id (`bill_ocr_eval`) so it sees
  the production rate limits as a single user (7 calls / 20s, 20 / min).
  Concurrency is capped at 2 with retry-on-bucket-full.
- Caching is by file presence; delete a raw file or pass `--no-cache`
  to force a re-run.
- Not registered in pytest. Run via `python -m tests.quality.bill_ocr.run`.
