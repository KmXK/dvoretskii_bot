# FINAL — Bill OCR prompt eval, Round 2

Round 2 hardened the corpus with 13 new cases that target real-world failure
modes the round-1 corpus didn't cover, then iterated the prompt once
(`v3_v2plus`). Stopped early after the OpenRouter daily key limit was
exhausted mid-run.

## Corpus delta

13 new cases added to `cases.yaml` (29 total). Each targets a specific
hypothesis about prompt weak spots:

| id | tag | failure mode targeted |
|---|---|---|
| `long_dialogue_mixed` | realistic | 8-line multi-turn chat with photo + voice + text interleaved |
| `complex_fractions_uneven` | fraction | Per-person amounts that don't divide evenly into kopecks (3/5 + 1/5 + 1/5 of 100) |
| `treat_someone` | edge | "угостил Диму" — semantic gift, no debt expected |
| `multi_currency_one_bill` | currency | Two items in BYN + USD mixed |
| `cancellation_in_dialogue` | realistic | Speaker corrects mid-dialogue ("стой, не пицца — суши") |
| `discount_applied` | edge | Discount math (120 → 100 effective total) |
| `person_left_early` | realistic | Two items, different debtor sets (Дима present for one, absent for second) |
| `same_item_separate_orders` | realistic | "Каждый заказал себе бургер" — one row per person |
| `tip_inclusive` | edge | "+чаевые 10%, всего 220" — fold tip into final, don't emit two rows |
| `alias_resolution` | directory | Speaker uses alias "Кир" — output canonical "Кирилл" |
| `negative_phrasing` | realistic | "Дима ничего не пил" — exclude Дима from debtor list |
| `conflicting_amounts` | edge | Voice says "сорок", photo shows "45.00" |
| `ocr_dense_receipt` | ocr | OCR with УНП, кассир, НДС, итого, безнал — 2 real items |

## Phase A results — v2_integer_qty on the FULL corpus (29 cases)

| prompt × model | google/gemini-2.5-flash | google/gemini-2.5-pro | x-ai/grok-4-fast | avg |
|---|---|---|---|---|
| `baseline` (orig 16 only — not re-run on new) | 0.958 | 0.983 | 0.994 | 0.978 |
| `v2_integer_qty` orig 16 | 1.000 | 0.983 | 1.000 | 0.994 |
| `v2_integer_qty` new 13 | 0.873 | 0.867 | 0.926 | 0.889 |
| **`v2_integer_qty` FULL 29** | **0.943** | **0.921** | **0.967** | **0.944** |

Stop criterion: avg ≥ 0.92 on 2 of 3 models. **All 3 models** are above 0.92
on v2 against the harder 29-case corpus, so v2 already passes the bar.

## Phase B — v3_v2plus prompt iteration (Flash only — daily limit hit)

`v3_v2plus.txt` adds 8 new rule blocks to v2:

```
+ Rules for "угостить" / treats / gifts (omit row, ask question)
+ Rules for settlements / past-debt repayments (don't emit)
+ Rules for "каждый заказал себе" (no phantom 4th row)
+ Rules for tips / service charges (fold percentage into items, not separate row)
+ Rules for discounts (use effective total, not original)
+ Rules for cancellations / corrections (final state only)
+ Rules for negative phrasing (explicit exclusions)
+ Rules for canonical names (output canonical, not alias)
+ Rules for multi-currency (face value + question)
+ Rules for conflicting amounts (prefer photo over voice)
+ Rules for OCR noise filtering (skip УНП, НДС, итого, etc.)
```

(diff: ~80 lines added between the "Per-person pricing" and "Determining
who paid" sections of v2; nothing removed.)

### v3_v2plus on Flash, new 13 cases (12 cached; ocr_dense_receipt errored)

| case | v2_integer_qty Flash | v3_v2plus Flash | delta |
|---|---|---|---|
| long_dialogue_mixed | 1.00 | 1.00 | — |
| complex_fractions_uneven | 1.00 | 1.00 | — |
| **treat_someone** | **0.10** | **1.00** | **+0.90** |
| multi_currency_one_bill | 0.75 | 0.43 | -0.32 |
| cancellation_in_dialogue | 1.00 | 1.00 | — |
| discount_applied | 1.00 | 1.00 | — |
| person_left_early | 1.00 | 1.00 | — |
| same_item_separate_orders | 0.90 | 0.90 | — |
| tip_inclusive | 1.00 | 1.00 | — |
| alias_resolution | 1.00 | 1.00 | — |
| negative_phrasing | 1.00 | 1.00 | — |
| conflicting_amounts | 0.60 | 0.60 | — |
| ocr_dense_receipt | 1.00 | ERR | — |
| **avg (12 comparable)** | **0.863** | **0.911** | **+0.048** |

Net win for v3 on the new corpus on Flash. v3 was NOT run on Pro/Grok or on
the original 16 cases — the OpenRouter daily key limit (403 errors) hit
mid-run.

## Concrete failure excerpts

`treat_someone` × `v2_integer_qty` × all 3 models — model emits Дима as
debtor of 8 BYN, missing the gift semantics:

```
Кофе | 8 | 1 | Дима | Кирилл | Текст |
```

After v3_v2plus on Flash — fixed:

```
[ОБЩЕЕ]                                       (empty)
[ВОПРОСЫ]
Как записать угощение Димы кофе на 8? | Подарок (никто не должен) | Дима должен Кириллу 8 | Другое
```

`same_item_separate_orders` × Flash — phantom "Кто заказал четвёртый
бургер?" question even after v3 added an explicit "do not ask" rule:

```
Бургер | 15 | 1 | Кирилл | Паша | Текст |
Бургер | 15 | 1 | Дима   | Паша | Текст |
Бургер | 15 | 1 | Егор   | Паша | Текст |
Бургер | 15 | 1 | -      | Паша | Текст |
[ВОПРОСЫ]
Кто заказал четвертый бургер? | ...
```

Flash has a strong prior toward asking when the head-count seems off,
which the prompt couldn't override in one round. Gemini 2.5 Pro and Grok
both got this case at 1.00 on v2 — only Flash regresses.

`conflicting_amounts` × Flash — pre-splits price into two rows of 22.50
instead of a single 45 row, despite the v2 ban on fractional Кол-во and
v3's explicit "prefer photo" rule:

```
Пиво крафтовое | 22.50 | 1 | Кирилл | Кирилл | Голосовое | G1
Пиво крафтовое | 22.50 | 1 | Дима   | Кирилл | Голосовое | G1
```

This is the same Flash quirk seen in round 1 (`photo_ocr_lines` →
0.5 fractional Кол-во) — the model uses pre-divided prices via
single-debtor rows, which doesn't trip the integer-quantity guard but
breaks the `unit_price_minor` check. Could be fixed by adding "always
emit one row per item with all debtors comma-separated; never emit one
row per debtor for a shared item" — but that conflicts with the
fraction-share examples in the prompt.

## Recommendation

**Promote `v2_integer_qty` to production unchanged.** It scores 0.944
across the FULL hardened 29-case corpus — well above the 0.92
threshold — on all 3 models.

`v3_v2plus` is an experimental superset that demonstrably fixes
`treat_someone` (+0.90 on Flash) and adds rules for 8 other archetypes.
We could not validate v3 on Pro/Grok or on the original 16 cases due to
the OpenRouter daily limit. Before promoting v3, the user should:
1. Wait for limit reset.
2. Re-run v3 on Pro + Grok across the full 29 cases.
3. Verify nothing regresses on the original 16.
4. Decide whether the multi_currency_one_bill -0.32 on Flash (model
   drops the foreign-currency row entirely instead of emitting at face
   value) is acceptable — the v3 rule may have over-constrained Flash
   into a "don't emit" reading.

## Stop reason

OpenRouter daily key limit exhausted (HTTP 403 "Key limit exceeded
(daily limit)"). Per the brief's hard rules: "If you exhaust the
OpenRouter weekly key limit, STOP, write what you have, report."

Calls made this round: ~30 new (most were cache hits; the daily limit
was already partly consumed by prior eval work + prod usage).

## TL;DR

The hardened 29-case corpus reveals real failure modes (treat
semantics, multi-currency, OCR noise, Flash's tendency to pre-split
prices). v2_integer_qty already meets the 0.92 bar on all 3 models
against this harder corpus (avg 0.944), so the production prompt does
not need an urgent change. v3_v2plus is a promising superset
(treat_someone +0.90 on Flash) but needs a clean evaluation pass on
all 3 models before promotion.
