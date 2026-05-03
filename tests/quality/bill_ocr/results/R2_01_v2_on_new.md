# R2-01 v2_integer_qty on new cases

Cases: 13  Models: 3  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| v2_integer_qty | 0.842 | 0.917 | 0.892 | **0.884** |

## Per-case scores

### Prompt: `v2_integer_qty`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| long_dialogue_mixed | 1.00 | ERR | 1.00 |
| complex_fractions_uneven | 1.00 | 1.00 | 1.00 |
| treat_someone | 0.10 ✗ | 0.10 ✗ | 0.10 ✗ |
| multi_currency_one_bill | 0.50 ⚠ | 0.95 | 0.50 ⚠ |
| cancellation_in_dialogue | 1.00 | 1.00 | 1.00 |
| discount_applied | 1.00 | 1.00 | 1.00 |
| person_left_early | 1.00 | 1.00 | 1.00 |
| same_item_separate_orders | 0.90 | 1.00 | 1.00 |
| tip_inclusive | 1.00 | 0.95 | 1.00 |
| alias_resolution | 1.00 | 1.00 | 1.00 |
| negative_phrasing | 1.00 | 1.00 | 1.00 |
| conflicting_amounts | 0.60 ⚠ | 1.00 | 1.00 |
| ocr_dense_receipt | ERR | 1.00 | 1.00 |

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

### `multi_currency_one_bill` × `v2_integer_qty` × `google/gemini-2.5-flash` — score 0.50

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect the FIRST/dominant currency by amount/order — here BYN.
The second item ($30 taxi) should still be emitted (so we get the right
item count) — best interpretation is to convert price to the primary
currency or keep the amount and let the user fix later. We accept either
a row at price 30 (the dollar number) under BYN currency OR an extra
[ВОПРОСЫ] entry asking about currency.
_

- currency_ok=True items 1/1 per_person=0.00 creditor=1.00 questions_ok=False
- expected per-person: `{'Кирилл': 20000, 'Дима': 20000}`
- actual per-person:   `{'Дима': 21500}`

### `conflicting_amounts` × `v2_integer_qty` × `google/gemini-2.5-flash` — score 0.60

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

- currency_ok=True items 1/1 per_person=0.00 creditor=1.00 questions_ok=True

### `ocr_dense_receipt` × `v2_integer_qty` × `google/gemini-2.5-flash` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `long_dialogue_mixed` × `v2_integer_qty` × `google/gemini-2.5-pro` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

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

### `multi_currency_one_bill` × `v2_integer_qty` × `x-ai/grok-4-fast` — score 0.50

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect the FIRST/dominant currency by amount/order — here BYN.
The second item ($30 taxi) should still be emitted (so we get the right
item count) — best interpretation is to convert price to the primary
currency or keep the amount and let the user fix later. We accept either
a row at price 30 (the dollar number) under BYN currency OR an extra
[ВОПРОСЫ] entry asking about currency.
_

- currency_ok=True items 1/1 per_person=0.00 creditor=1.00 questions_ok=False
- expected per-person: `{'Кирилл': 20000, 'Дима': 20000}`
- actual per-person:   `{'Кирилл': 21500, 'Дима': 21500}`
