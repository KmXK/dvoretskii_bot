# FINAL — Bill OCR prompt eval

Cases: 16  Models: 3  Prompt variants: 2

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| baseline | 0.958 | 0.983 | 0.994 | **0.978** |
| v2_integer_qty | 1.000 | 0.983 | 1.000 | **0.994** |

## Per-case scores

### Prompt: `baseline`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| simple_pizza | 1.00 | 1.00 | 1.00 |
| two_creditors | 1.00 | 1.00 | 1.00 |
| hookah_quarter | 1.00 | 1.00 | 0.90 |
| hookah_half | 1.00 | 1.00 | 1.00 |
| hookah_third | 1.00 | 1.00 | 1.00 |
| two_hookahs_subgroups | 1.00 | 1.00 | 1.00 |
| partial_quantity | 0.73 ⚠ | 0.73 ⚠ | 1.00 |
| explicit_pop | 1.00 | 1.00 | 1.00 |
| voice_noise | 1.00 | 1.00 | 1.00 |
| photo_ocr_lines | 0.60 ⚠ | 1.00 | 1.00 |
| rouble_currency | 1.00 | 1.00 | 1.00 |
| dollar_currency | 1.00 | 1.00 | 1.00 |
| unknown_participant | 1.00 | 1.00 | 1.00 |
| ambiguous_no_creditor | 1.00 | 1.00 | 1.00 |
| missing_amount | 1.00 | 1.00 | 1.00 |
| per_person_pricing | 1.00 | 1.00 | 1.00 |

### Prompt: `v2_integer_qty`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| simple_pizza | 1.00 | 1.00 | 1.00 |
| two_creditors | 1.00 | 1.00 | 1.00 |
| hookah_quarter | 1.00 | 0.73 ⚠ | 1.00 |
| hookah_half | 1.00 | 1.00 | 1.00 |
| hookah_third | 1.00 | 1.00 | 1.00 |
| two_hookahs_subgroups | 1.00 | 1.00 | 1.00 |
| partial_quantity | 1.00 | 1.00 | 1.00 |
| explicit_pop | 1.00 | 1.00 | 1.00 |
| voice_noise | 1.00 | 1.00 | 1.00 |
| photo_ocr_lines | 1.00 | 1.00 | 1.00 |
| rouble_currency | 1.00 | 1.00 | 1.00 |
| dollar_currency | 1.00 | 1.00 | 1.00 |
| unknown_participant | 1.00 | 1.00 | 1.00 |
| ambiguous_no_creditor | 1.00 | 1.00 | 1.00 |
| missing_amount | 1.00 | 1.00 | 1.00 |
| per_person_pricing | 1.00 | 1.00 | 1.00 |

## Failure detail (score < 0.7)

### `photo_ocr_lines` × `baseline` × `google/gemini-2.5-flash` — score 0.60

_receipt OCR style with prices on separate lines and service tax_

- currency_ok=True items 4/4 per_person=0.00 creditor=1.00 questions_ok=True
- expected per-person: `{'Кирилл': 1650, 'Дима': 1650}`
- actual per-person:   `{'Кирилл': 3300, 'Дима': 3300}`

---

## TL;DR

**Best prompt:** `tests/quality/bill_ocr/prompts/v2_integer_qty.txt` — average **0.994** vs baseline **0.978** (+0.016 absolute, all from Flash and Grok improvements).

### Per-model deltas

| model | baseline | v2_integer_qty | delta |
|---|---|---|---|
| google/gemini-2.5-flash | 0.958 | **1.000** | +0.042 |
| google/gemini-2.5-pro | 0.983 | 0.983 | 0.000 (truncation) |
| x-ai/grok-4-fast | 0.994 | **1.000** | +0.006 |

### What v2 fixed

The baseline let models reach for fractional `Кол-во` (e.g. `0.5`, `1.5`)
to express splits, but the production parser rounds to integer and
silently doubles the bill (`0.5 → 1`). v2 explicitly bans fractional
`Кол-во` and forces share-via-price encoding. Two cases that broke
on baseline (Flash `photo_ocr_lines` → 0.60, Flash/Pro
`partial_quantity` → 0.73) score perfectly under v2.

The currency rule was also tightened so that "рублей" alone stays
BYN. Grok had a single-case currency leak under baseline
(`hookah_quarter` → RUB) that v2 eliminates.

### Top remaining failure modes

1. **Gemini 2.5 Pro at max_tokens=2048 truncates** — the model uses
   internal reasoning that consumes the output budget, so structured
   outputs get cut mid-line. `hookah_quarter` and `hookah_third` both
   showed mid-row truncation. **Production already uses 4096**, so
   this is an eval-harness-only artifact, but worth noting: Pro under
   tight output budgets is unreliable. The user should keep `max_tokens`
   at 4096 in production for Pro.

2. **Slang naming** — Pro emitted "Калик" (hookah slang) when the
   source text used that word, and "Бургер" vs "Бургер двойной" matters
   for fuzzy match. The prompt could nudge toward canonical naming
   (e.g. always "Кальян" not "Калик"), but real-world UX may prefer
   slang fidelity. Not addressed in v2.

3. **Receipt totals that include service charges**: the photo_ocr
   case includes a "Подытог" + "Итого" + "Обслуживание зала 10%". v2
   handles this perfectly, but with more complex receipts (multi-page,
   discounts, refunds) more cases would be needed.

### Recommendation

If the user wants to update production: **review and
copy `tests/quality/bill_ocr/prompts/v2_integer_qty.txt` to
`prompts/bill_ocr.txt`**. The two changes vs baseline are:

- The `Кол-во` rule now bans fractional values and shows price-based
  share examples.
- The `[META] currency` rule is more explicit that "рублей" alone is
  BYN.

Both are conservative additions with no downside in the test corpus.
