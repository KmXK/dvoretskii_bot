# R2 v3_v2plus FULL corpus Flash only

Cases: 29  Models: 1  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | avg |
|---|---|---|
| v3_v2plus | 0.910 | **0.910** |

## Per-case scores

### Prompt: `v3_v2plus`

| case | google/gemini-2.5-flash |
|---|---|
| simple_pizza | ERR |
| two_creditors | ERR |
| hookah_quarter | ERR |
| hookah_half | ERR |
| hookah_third | ERR |
| two_hookahs_subgroups | ERR |
| partial_quantity | ERR |
| explicit_pop | ERR |
| voice_noise | ERR |
| photo_ocr_lines | ERR |
| rouble_currency | ERR |
| dollar_currency | ERR |
| unknown_participant | ERR |
| ambiguous_no_creditor | ERR |
| missing_amount | ERR |
| per_person_pricing | ERR |
| long_dialogue_mixed | 1.00 |
| complex_fractions_uneven | 1.00 |
| treat_someone | 1.00 |
| multi_currency_one_bill | 0.43 ✗ |
| cancellation_in_dialogue | 1.00 |
| discount_applied | 1.00 |
| person_left_early | 1.00 |
| same_item_separate_orders | 0.90 |
| tip_inclusive | 1.00 |
| alias_resolution | 1.00 |
| negative_phrasing | 1.00 |
| conflicting_amounts | 0.60 ⚠ |
| ocr_dense_receipt | ERR |

## Failure detail (score < 0.7)

### `simple_pizza` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_3 people equal split, single payer_

**ERROR:** budget_exceeded

### `two_creditors` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_two distinct payers in same context_

**ERROR:** budget_exceeded

### `hookah_quarter` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_fractional consumption — speaker took 1/4, two others split rest equally_

**ERROR:** budget_exceeded

### `hookah_half` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_fractional — speaker took half, friend took half, friend paid_

**ERROR:** budget_exceeded

### `hookah_third` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_speaker owes one third, other person paid_

**ERROR:** budget_exceeded

### `two_hookahs_subgroups` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_2 hookahs, different debtor sets_

**ERROR:** budget_exceeded

### `partial_quantity` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_5 sushi portions, speaker ate 2 of 5_

**ERROR:** budget_exceeded

### `explicit_pop` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_пиццу пополам с Димой_

**ERROR:** budget_exceeded

### `voice_noise` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_voice transcript with disfluencies, repetitions_

**ERROR:** budget_exceeded

### `photo_ocr_lines` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_receipt OCR style with prices on separate lines and service tax_

**ERROR:** budget_exceeded

### `rouble_currency` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_explicit Russian roubles_

**ERROR:** budget_exceeded

### `dollar_currency` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_explicit USD_

**ERROR:** budget_exceeded

### `unknown_participant` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_directory missing someone → expect questions or unknown debtor_

**ERROR:** budget_exceeded

### `ambiguous_no_creditor` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_купили в баре, no payer named → "-" creditor + question_

**ERROR:** budget_exceeded

### `missing_amount` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_speaker mentions tip but no amount → question, no row_

**ERROR:** budget_exceeded

### `per_person_pricing` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_po N rubley — N per person_

**ERROR:** budget_exceeded

### `multi_currency_one_bill` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.43

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

- currency_ok=True items 1/2 per_person=0.00 creditor=0.50 questions_ok=True
- expected per-person: `{'Кирилл': 21500, 'Дима': 21500}`
- actual per-person:   `{'Кирилл': 20000, 'Дима': 20000}`

### `conflicting_amounts` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.60

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

- currency_ok=True items 1/1 per_person=0.00 creditor=1.00 questions_ok=True

### `ocr_dense_receipt` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** budget_exceeded
