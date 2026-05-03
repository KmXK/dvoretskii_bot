# Bill OCR Eval

Cases: 1  Models: 1  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | avg |
|---|---|---|
| v3_v2plus | 0.000 | **0.000** |

## Per-case scores

### Prompt: `v3_v2plus`

| case | google/gemini-2.5-flash |
|---|---|
| ocr_dense_receipt | ERR |

## Failure detail (score < 0.7)

### `ocr_dense_receipt` × `v3_v2plus` × `google/gemini-2.5-flash` — score 0.00

_dense OCR with many service lines, totals, taxes — only 2 real items_

**ERROR:** PermissionDeniedError: Error code: 403 - {'error': {'message': 'Key limit exceeded (daily limit). Manage it using https://openrouter.ai/settings/keys', 'code': 403}}
