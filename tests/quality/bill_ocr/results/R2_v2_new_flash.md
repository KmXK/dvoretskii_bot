# Bill OCR Eval

Cases: 13  Models: 1  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | avg |
|---|---|---|
| v2_integer_qty | 0.873 | **0.873** |

## Per-case scores

### Prompt: `v2_integer_qty`

| case | google/gemini-2.5-flash |
|---|---|
| long_dialogue_mixed | 1.00 |
| complex_fractions_uneven | 1.00 |
| treat_someone | 0.10 ✗ |
| multi_currency_one_bill | 0.75 ⚠ |
| cancellation_in_dialogue | 1.00 |
| discount_applied | 1.00 |
| person_left_early | 1.00 |
| same_item_separate_orders | 0.90 |
| tip_inclusive | 1.00 |
| alias_resolution | 1.00 |
| negative_phrasing | 1.00 |
| conflicting_amounts | 0.60 ⚠ |
| ocr_dense_receipt | 1.00 |

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
