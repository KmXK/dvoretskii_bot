# v3 compact run

Cases: 16  Models: 3  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| v3_compact | 0.967 | 0.967 | 0.000 | **0.644** |

## Per-case scores

### Prompt: `v3_compact`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| simple_pizza | 1.00 | 1.00 | ERR |
| two_creditors | 1.00 | 1.00 | ERR |
| hookah_quarter | 1.00 | 1.00 | ERR |
| hookah_half | 1.00 | 0.80 ⚠ | ERR |
| hookah_third | 1.00 | 1.00 | ERR |
| two_hookahs_subgroups | 1.00 | 1.00 | ERR |
| partial_quantity | 0.73 ⚠ | ERR | ERR |
| explicit_pop | 1.00 | ERR | ERR |
| voice_noise | 1.00 | ERR | ERR |
| photo_ocr_lines | 0.80 ⚠ | ERR | ERR |
| rouble_currency | 1.00 | ERR | ERR |
| dollar_currency | 1.00 | ERR | ERR |
| unknown_participant | 1.00 | ERR | ERR |
| ambiguous_no_creditor | 1.00 | ERR | ERR |
| missing_amount | ERR | ERR | ERR |
| per_person_pricing | ERR | ERR | ERR |

## Failure detail (score < 0.7)

### `missing_amount` × `v3_compact` × `google/gemini-2.5-flash` — score 0.00

_speaker mentions tip but no amount → question, no row_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `per_person_pricing` × `v3_compact` × `google/gemini-2.5-flash` — score 0.00

_po N rubley — N per person_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `partial_quantity` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_5 sushi portions, speaker ate 2 of 5_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `explicit_pop` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_пиццу пополам с Димой_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `voice_noise` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_voice transcript with disfluencies, repetitions_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `photo_ocr_lines` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_receipt OCR style with prices on separate lines and service tax_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `rouble_currency` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_explicit Russian roubles_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `dollar_currency` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_explicit USD_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `unknown_participant` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_directory missing someone → expect questions or unknown debtor_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `ambiguous_no_creditor` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_купили в баре, no payer named → "-" creditor + question_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `missing_amount` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_speaker mentions tip but no amount → question, no row_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `per_person_pricing` × `v3_compact` × `google/gemini-2.5-pro` — score 0.00

_po N rubley — N per person_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `simple_pizza` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_3 people equal split, single payer_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `two_creditors` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_two distinct payers in same context_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `hookah_quarter` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_fractional consumption — speaker took 1/4, two others split rest equally_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `hookah_half` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_fractional — speaker took half, friend took half, friend paid_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `hookah_third` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_speaker owes one third, other person paid_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `two_hookahs_subgroups` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_2 hookahs, different debtor sets_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `partial_quantity` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_5 sushi portions, speaker ate 2 of 5_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `explicit_pop` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_пиццу пополам с Димой_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `voice_noise` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_voice transcript with disfluencies, repetitions_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `photo_ocr_lines` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_receipt OCR style with prices on separate lines and service tax_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `rouble_currency` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_explicit Russian roubles_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full

### `dollar_currency` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_explicit USD_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `unknown_participant` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_directory missing someone → expect questions or unknown debtor_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `ambiguous_no_creditor` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_купили в баре, no payer named → "-" creditor + question_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `missing_amount` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_speaker mentions tip but no amount → question, no row_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}

### `per_person_pricing` × `v3_compact` × `x-ai/grok-4-fast` — score 0.00

_po N rubley — N per person_

**ERROR:** BucketFullException: Bucket for item= with Rate limit=20/1.0m is already full
