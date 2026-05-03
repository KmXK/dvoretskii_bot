# R2-02 v3_v2plus on new cases

Cases: 13  Models: 3  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| v3_v2plus | 0.910 | 0.000 | 0.000 | **0.303** |

## Per-case scores

### Prompt: `v3_v2plus`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| long_dialogue_mixed | 1.00 | ERR | ERR |
| complex_fractions_uneven | 1.00 | ERR | ERR |
| treat_someone | 1.00 | ERR | ERR |
| multi_currency_one_bill | 0.43 ✗ | ERR | ERR |
| cancellation_in_dialogue | 1.00 | ERR | ERR |
| discount_applied | 1.00 | ERR | ERR |
| person_left_early | 1.00 | ERR | ERR |
| same_item_separate_orders | 0.90 | ERR | ERR |
| tip_inclusive | 1.00 | ERR | ERR |
| alias_resolution | 1.00 | ERR | ERR |
| negative_phrasing | 1.00 | ERR | ERR |
| conflicting_amounts | 0.60 ⚠ | ERR | ERR |
| ocr_dense_receipt | ERR | ERR | ERR |

## Failure detail (score < 0.7)

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

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `long_dialogue_mixed` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `complex_fractions_uneven` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_uneven fractional consumption that doesn't divide evenly into kopecks_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `treat_someone` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `multi_currency_one_bill` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `cancellation_in_dialogue` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_speaker corrects a prior statement; final state is sushi only_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `discount_applied` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_Bill total 120, discount applied → effective total 100 split 3 ways.
33.33 each → expressed as 33/33/34 OR 33.33 each. We accept either.
Test passes if per-person totals sum to 100 ± rounding and each person ~3333 kopecks.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `person_left_early` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_two items with different debtor sets — Дима participated only in first_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `same_item_separate_orders` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_each person orders own burger, same price — 4 single-debtor rows OR 1 grouped row_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `tip_inclusive` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_bill plus tip percentage applied — per-person 55, not 50_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `alias_resolution` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_Speaker uses an alias; model must canonicalize to display_name.
Directory has Кирилл with aliases [Кир, Кирыч].
Expected: model emits 'Кирилл' as creditor, NOT 'Кир'.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `negative_phrasing` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_speaker excludes someone explicitly — "Дима ничего не пил"_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `conflicting_amounts` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `ocr_dense_receipt` × `v3_v2plus` × `google/gemini-2.5-pro` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `long_dialogue_mixed` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `complex_fractions_uneven` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_uneven fractional consumption that doesn't divide evenly into kopecks_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `treat_someone` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_Speaker treats a friend ("угостил Диму") — interpreted as Дима owes nothing,
item only registered as a record but with zero debtors. Picking the
"no-row + question" interpretation: prompt should ask whether to record
a one-sided gift, since the bill system splits debt.
Defensible alternative: emit row with creditor=Кирилл, debtors=Дима (Дима owes
Кирилл) — but "угостил" idiomatically means Дима DOES NOT owe.
We pick the latter: debtors=[] (or '-'), no debt registered. We accept
EITHER 0 items + question, OR 1 item with debtors='-' + question.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `multi_currency_one_bill` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_Two items in two different currencies in the same context.
The [META] currency block is single-valued, so the prompt must pick ONE
primary. We expect BYN as primary (dominant by amount/order). The
defensible behavior is to emit BOTH items at face value under BYN
AND ask a clarifying question about the dollar item. We score on the
кальян only (per-person); spurious penalty allows for one extra row.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `cancellation_in_dialogue` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_speaker corrects a prior statement; final state is sushi only_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `discount_applied` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_Bill total 120, discount applied → effective total 100 split 3 ways.
33.33 each → expressed as 33/33/34 OR 33.33 each. We accept either.
Test passes if per-person totals sum to 100 ± rounding and each person ~3333 kopecks.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `person_left_early` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_two items with different debtor sets — Дима participated only in first_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `same_item_separate_orders` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_each person orders own burger, same price — 4 single-debtor rows OR 1 grouped row_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `tip_inclusive` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_bill plus tip percentage applied — per-person 55, not 50_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `alias_resolution` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_Speaker uses an alias; model must canonicalize to display_name.
Directory has Кирилл with aliases [Кир, Кирыч].
Expected: model emits 'Кирилл' as creditor, NOT 'Кир'.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `negative_phrasing` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_speaker excludes someone explicitly — "Дима ничего не пил"_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `conflicting_amounts` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_Voice says "сорок", photo line shows "45.00". Documented expected behavior:
model picks ONE (preferably the photo as more authoritative) OR emits
a [ВОПРОСЫ] entry asking which is correct. Penalize only if both items
are emitted as separate rows.
We accept either price 4000 or 4500 minor units.
_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `ocr_dense_receipt` × `v3_v2plus` × `x-ai/grok-4-fast` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}
