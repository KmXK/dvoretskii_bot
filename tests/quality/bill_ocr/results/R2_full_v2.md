# R2 v2_integer_qty FULL corpus (29 cases)

Cases: 29  Models: 3  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| v2_integer_qty | 0.943 | 0.921 | 0.967 | **0.944** |

## Per-case scores

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
| long_dialogue_mixed | 1.00 | 0.56 ⚠ | 1.00 |
| complex_fractions_uneven | 1.00 | 1.00 | 1.00 |
| treat_someone | 0.10 ✗ | 0.10 ✗ | 0.10 ✗ |
| multi_currency_one_bill | 0.75 ⚠ | 0.38 ✗ | 0.95 |
| cancellation_in_dialogue | 1.00 | 1.00 | 1.00 |
| discount_applied | 1.00 | 1.00 | 1.00 |
| person_left_early | 1.00 | 1.00 | 1.00 |
| same_item_separate_orders | 0.90 | 1.00 | 1.00 |
| tip_inclusive | 1.00 | 0.95 | 1.00 |
| alias_resolution | 1.00 | 1.00 | 1.00 |
| negative_phrasing | 1.00 | 1.00 | 1.00 |
| conflicting_amounts | 0.60 ⚠ | 1.00 | 1.00 |
| ocr_dense_receipt | 1.00 | 1.00 | 1.00 |

## Failure detail (score < 0.7)

### `treat_someone` × `v2_integer_qty` × `google/gemini-2.5-flash` — score 0.10

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

- currency_ok=True items 0/0 per_person=0.00 creditor=0.00 questions_ok=False

### `conflicting_amounts` × `v2_integer_qty` × `google/gemini-2.5-flash` — score 0.60

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

- currency_ok=True items 1/1 per_person=0.00 creditor=1.00 questions_ok=True

### `long_dialogue_mixed` × `v2_integer_qty` × `google/gemini-2.5-pro` — score 0.56

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

- currency_ok=True items 1/2 per_person=0.33 creditor=0.50 questions_ok=True
- expected per-person: `{'Кирилл': 1200, 'Дима': 2400, 'Егор': 2400}`
- actual per-person:   `{'Кирилл': 1200, 'Дима': 1200, 'Егор': 1200}`

### `treat_someone` × `v2_integer_qty` × `google/gemini-2.5-pro` — score 0.10

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

- currency_ok=True items 0/0 per_person=0.00 creditor=0.00 questions_ok=False

### `multi_currency_one_bill` × `v2_integer_qty` × `google/gemini-2.5-pro` — score 0.38

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

- currency_ok=True items 1/2 per_person=0.00 creditor=0.50 questions_ok=False
- expected per-person: `{'Кирилл': 21500, 'Дима': 21500}`
- actual per-person:   `{'Кирилл': 20000, 'Дима': 20000}`

### `treat_someone` × `v2_integer_qty` × `x-ai/grok-4-fast` — score 0.10

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

- currency_ok=True items 0/0 per_person=0.00 creditor=0.00 questions_ok=False
