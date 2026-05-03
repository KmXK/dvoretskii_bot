# Bill OCR Eval

Cases: 2  Models: 2  Prompt variants: 1

## Summary (avg score per prompt × model)

| prompt \ model | google/gemini-2.5-flash | google/gemini-2.5-pro | avg |
|---|---|---|---|
| v2_integer_qty | 1.000 | 0.779 | **0.890** |

## Per-case scores

### Prompt: `v2_integer_qty`

| case | google/gemini-2.5-flash | google/gemini-2.5-pro |
|---|---|---|
| long_dialogue_mixed | 1.00 | 0.56 ⚠ |
| ocr_dense_receipt | 1.00 | 1.00 |

## Failure detail (score < 0.7)

### `long_dialogue_mixed` × `v2_integer_qty` × `google/gemini-2.5-pro` — score 0.56

_8-line multi-turn dialogue with text + photo OCR + voice snippets interleaved_

- currency_ok=True items 1/2 per_person=0.33 creditor=0.50 questions_ok=True
- expected per-person: `{'Кирилл': 1200, 'Дима': 2400, 'Егор': 2400}`
- actual per-person:   `{'Кирилл': 1200, 'Дима': 1200, 'Егор': 1200}`
