# v3 compact (partial — API key budget)

Cases: 14  Models: 2  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | avg |
|---|---|---|---|
| v3_compact | 0.967 | 0.967 | **0.967** |

## Per-case scores

### Prompt: `v3_compact`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro |
|---|---|---|
| simple_pizza | 1.00 | 1.00 |
| two_creditors | 1.00 | 1.00 |
| hookah_quarter | 1.00 | 1.00 |
| hookah_half | 1.00 | 0.80 ⚠ |
| hookah_third | 1.00 | 1.00 |
| two_hookahs_subgroups | 1.00 | 1.00 |
| partial_quantity | 0.73 ⚠ | ERR |
| explicit_pop | 1.00 | ERR |
| voice_noise | 1.00 | ERR |
| photo_ocr_lines | 0.80 ⚠ | ERR |
| rouble_currency | 1.00 | ERR |
| dollar_currency | 1.00 | ERR |
| unknown_participant | 1.00 | ERR |
| ambiguous_no_creditor | 1.00 | ERR |

## Failure detail (score < 0.7)

### `partial_quantity` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_5 sushi portions, speaker ate 2 of 5_

**ERROR:** budget_exceeded

### `explicit_pop` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_пиццу пополам с Димой_

**ERROR:** budget_exceeded

### `voice_noise` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_voice transcript with disfluencies, repetitions_

**ERROR:** budget_exceeded

### `photo_ocr_lines` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_receipt OCR style with prices on separate lines and service tax_

**ERROR:** budget_exceeded

### `rouble_currency` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_explicit Russian roubles_

**ERROR:** budget_exceeded

### `dollar_currency` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_explicit USD_

**ERROR:** budget_exceeded

### `unknown_participant` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_directory missing someone → expect questions or unknown debtor_

**ERROR:** budget_exceeded

### `ambiguous_no_creditor` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_купили в баре, no payer named → "-" creditor + question_

**ERROR:** budget_exceeded
