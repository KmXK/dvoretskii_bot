# v2 integer-qty on failing cases

Cases: 5  Models: 3  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| v2_integer_qty | 0.980 | 0.947 | 0.990 | **0.972** |

## Per-case scores

### Prompt: `v2_integer_qty`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast |
|---|---|---|---|
| hookah_quarter | 0.95 | 0.73 ⚠ | 0.95 |
| two_hookahs_subgroups | 0.95 | 1.00 | 1.00 |
| partial_quantity | 1.00 | 1.00 | 1.00 |
| photo_ocr_lines | 1.00 | 1.00 | 1.00 |
| missing_amount | 1.00 | 1.00 | 1.00 |

## Failure detail (score < 0.7)
