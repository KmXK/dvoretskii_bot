# R2 baseline vs v2 FULL corpus

Cases: 29  Models: 3  Prompt variants: 2

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| baseline | 0.958 | 0.983 | 0.994 | **0.978** |
| v2_integer_qty | 0.943 | 0.921 | 0.967 | **0.944** |

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
| long_dialogue_mixed | ERR | ERR | ERR |
| complex_fractions_uneven | ERR | ERR | ERR |
| treat_someone | ERR | ERR | ERR |
| multi_currency_one_bill | ERR | ERR | ERR |
| cancellation_in_dialogue | ERR | ERR | ERR |
| discount_applied | ERR | ERR | ERR |
| person_left_early | ERR | ERR | ERR |
| same_item_separate_orders | ERR | ERR | ERR |
| tip_inclusive | ERR | ERR | ERR |
| alias_resolution | ERR | ERR | ERR |
| negative_phrasing | ERR | ERR | ERR |
| conflicting_amounts | ERR | ERR | ERR |
| ocr_dense_receipt | ERR | ERR | ERR |

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

### `photo_ocr_lines` × `baseline` × `google/gemini-2.5-flash` — score 0.60

_receipt OCR style with prices on separate lines and service tax_

- currency_ok=True items 4/4 per_person=0.00 creditor=1.00 questions_ok=True
- expected per-person: `{'Кирилл': 1650, 'Дима': 1650}`
- actual per-person:   `{'Кирилл': 3300, 'Дима': 3300}`

### `long_dialogue_mixed` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** budget_exceeded

### `complex_fractions_uneven` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_uneven fractional consumption that doesn't divide evenly into kopecks_

**ERROR:** budget_exceeded

### `treat_someone` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

**ERROR:** budget_exceeded

### `multi_currency_one_bill` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

**ERROR:** budget_exceeded

### `cancellation_in_dialogue` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_speaker corrects a prior statement; final state is sushi only_

**ERROR:** budget_exceeded

### `discount_applied` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_Bill total 120, discount applied → effective total 100 split 3 ways.
33.33 each → expressed as 33/33/34 OR 33.33 each. We accept either.
Test passes if per-person totals sum to 100 ± rounding and each person ~3333 kopecks.
_

**ERROR:** budget_exceeded

### `person_left_early` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_two items with different debtor sets — Дима participated only in first_

**ERROR:** budget_exceeded

### `same_item_separate_orders` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_each person orders own burger, same price — 4 single-debtor rows OR 1 grouped row_

**ERROR:** budget_exceeded

### `tip_inclusive` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_bill plus tip percentage applied — per-person 55, not 50_

**ERROR:** budget_exceeded

### `alias_resolution` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_Speaker uses an alias; model must canonicalize to display_name.
Directory has Кирилл with aliases [Кир, Кирыч].
Expected: model emits 'Кирилл' as creditor, NOT 'Кир'.
_

**ERROR:** budget_exceeded

### `negative_phrasing` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_speaker excludes someone explicitly — "Дима ничего не пил"_

**ERROR:** budget_exceeded

### `conflicting_amounts` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

**ERROR:** budget_exceeded

### `ocr_dense_receipt` × `baseline` × `google/gemini-2.5-flash` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** budget_exceeded

### `long_dialogue_mixed` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** budget_exceeded

### `complex_fractions_uneven` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_uneven fractional consumption that doesn't divide evenly into kopecks_

**ERROR:** budget_exceeded

### `treat_someone` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

**ERROR:** budget_exceeded

### `multi_currency_one_bill` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

**ERROR:** budget_exceeded

### `cancellation_in_dialogue` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_speaker corrects a prior statement; final state is sushi only_

**ERROR:** budget_exceeded

### `discount_applied` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_Bill total 120, discount applied → effective total 100 split 3 ways.
33.33 each → expressed as 33/33/34 OR 33.33 each. We accept either.
Test passes if per-person totals sum to 100 ± rounding and each person ~3333 kopecks.
_

**ERROR:** budget_exceeded

### `person_left_early` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_two items with different debtor sets — Дима participated only in first_

**ERROR:** budget_exceeded

### `same_item_separate_orders` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_each person orders own burger, same price — 4 single-debtor rows OR 1 grouped row_

**ERROR:** budget_exceeded

### `tip_inclusive` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_bill plus tip percentage applied — per-person 55, not 50_

**ERROR:** budget_exceeded

### `alias_resolution` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_Speaker uses an alias; model must canonicalize to display_name.
Directory has Кирилл with aliases [Кир, Кирыч].
Expected: model emits 'Кирилл' as creditor, NOT 'Кир'.
_

**ERROR:** budget_exceeded

### `negative_phrasing` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_speaker excludes someone explicitly — "Дима ничего не пил"_

**ERROR:** budget_exceeded

### `conflicting_amounts` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

**ERROR:** budget_exceeded

### `ocr_dense_receipt` × `baseline` × `google/gemini-2.5-pro` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** budget_exceeded

### `long_dialogue_mixed` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** budget_exceeded

### `complex_fractions_uneven` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_uneven fractional consumption that doesn't divide evenly into kopecks_

**ERROR:** budget_exceeded

### `treat_someone` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

**ERROR:** budget_exceeded

### `multi_currency_one_bill` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

**ERROR:** budget_exceeded

### `cancellation_in_dialogue` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_speaker corrects a prior statement; final state is sushi only_

**ERROR:** budget_exceeded

### `discount_applied` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_Bill total 120, discount applied → effective total 100 split 3 ways.
33.33 each → expressed as 33/33/34 OR 33.33 each. We accept either.
Test passes if per-person totals sum to 100 ± rounding and each person ~3333 kopecks.
_

**ERROR:** budget_exceeded

### `person_left_early` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_two items with different debtor sets — Дима participated only in first_

**ERROR:** budget_exceeded

### `same_item_separate_orders` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_each person orders own burger, same price — 4 single-debtor rows OR 1 grouped row_

**ERROR:** budget_exceeded

### `tip_inclusive` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_bill plus tip percentage applied — per-person 55, not 50_

**ERROR:** budget_exceeded

### `alias_resolution` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_Speaker uses an alias; model must canonicalize to display_name.
Directory has Кирилл with aliases [Кир, Кирыч].
Expected: model emits 'Кирилл' as creditor, NOT 'Кир'.
_

**ERROR:** budget_exceeded

### `negative_phrasing` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_speaker excludes someone explicitly — "Дима ничего не пил"_

**ERROR:** budget_exceeded

### `conflicting_amounts` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

**ERROR:** budget_exceeded

### `ocr_dense_receipt` × `baseline` × `x-ai/grok-4-fast` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** budget_exceeded
