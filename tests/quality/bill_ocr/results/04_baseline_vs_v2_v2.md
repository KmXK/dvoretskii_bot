# Baseline vs v2 (after scoring fix)

Cases: 16  Models: 3  Prompt variants: 2

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| baseline | 0.955 | 0.983 | 0.994 | **0.977** |
| v2_integer_qty | 0.997 | 0.983 | 1.000 | **0.993** |

## Per-case scores

### Prompt: `baseline`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| simple_pizza | 1.00 | 1.00 | 1.00 |
| two_creditors | 1.00 | 1.00 | 1.00 |
| hookah_quarter | 1.00 | 1.00 | 0.90 |
| hookah_half | 1.00 | 1.00 | 1.00 |
| hookah_third | 1.00 | 1.00 | 1.00 |
| two_hookahs_subgroups | 0.95 | 1.00 | 1.00 |
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
| two_hookahs_subgroups | 0.95 | 1.00 | 1.00 |
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
