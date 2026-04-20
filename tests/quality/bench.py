import asyncio
import os
import time
from pathlib import Path

_env_path = Path(__file__).parents[2] / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k == "DOWNLOAD_PROXY":
            continue
        os.environ.setdefault(k, v)

from steward.helpers.ai import (  # noqa: E402
    Model,
    YandexModelTypes,
    make_nvidia_query,
    make_openrouter_query,
    make_yandex_ai_query,
    resolve_model,
)

PROMPTS: list[tuple[str, str, str, str]] = [
    (
        "router",
        "smart",
        "Ты — диспетчер команд Telegram-бота. На вход получаешь просьбу от пользователя, "
        "возвращаешь одну подходящую команду с аргументами. Доступные команды:\n"
        "/bill add <сумма> <описание>\n"
        "/weather <город>\n"
        "/joke\n"
        "/ai <вопрос>\n"
        "Верни ТОЛЬКО команду, без пояснений.",
        "дворецкий, добавь счёт на 1200 рублей за пиво в бар-кафе Сидр",
    ),
    (
        "grok_chat",
        "smart",
        "Ты — колкий язвительный ИИ в чате друзей. Отвечай коротко (1-2 фразы), "
        "с сарказмом и матом где уместно, но по делу. Без воды и извинений.",
        "Я сегодня опять проспал планёрку. Что делать?",
    ),
    (
        "pasha",
        "smart",
        "Ты — мрачный философ-алкоголик по имени Паша. Говоришь с едким юмором, "
        "любишь портвейн и Достоевского. 2-3 предложения.",
        "Паша, как жить если всё — тлен?",
    ),
    (
        "summary",
        "fast",
        "Сделай ОЧЕНЬ краткую выжимку голосового сообщения. Максимум 1-2 предложения, "
        "только суть. Без вступлений, без форматирования, без кавычек.",
        "Короче смотри я сейчас еду в метро на красной ветке и понял что забыл зарядку "
        "от ноута дома на кухне на столе рядом с чайником а у меня через час встреча "
        "по зуму с клиентом из Лондона это же полная задница вот я и думаю может ты "
        "сможешь подвезти зарядку ну там макбуковскую 96 ватт в офис на Кутузовский "
        "до часа дня иначе я буду пытаться дотянуть на остатке батареи хз доживу или нет",
    ),
    (
        "birthday",
        "smart",
        "Поздравь с днём рождения коротко, ярко, с юмором. Без банальщины и пафоса. "
        "2-3 предложения максимум, разговорно.",
        "Поздравь Пашу",
    ),
]


async def _call_nvidia(tier: str, system: str, user: str) -> tuple[str, float]:
    model = resolve_model(Model.SMART if tier == "smart" else Model.FAST, "nvidia")
    t0 = time.perf_counter()
    text = await make_nvidia_query(0, model, [("user", user)], system)
    return text, time.perf_counter() - t0


async def _call_openrouter(tier: str, system: str, user: str) -> tuple[str, float]:
    model = resolve_model(Model.SMART if tier == "smart" else Model.FAST, "openrouter")
    t0 = time.perf_counter()
    text = await make_openrouter_query(0, model, [("user", user)], system)
    return text, time.perf_counter() - t0


async def _call_yandex(tier: str, system: str, user: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    text = await make_yandex_ai_query(
        0, [("user", user)], system, YandexModelTypes.YANDEXGPT_5_PRO
    )
    return text, time.perf_counter() - t0


async def _run_one(provider: str, tier: str, system: str, user: str) -> dict:
    call = {"nvidia": _call_nvidia, "openrouter": _call_openrouter, "yandex": _call_yandex}[provider]
    try:
        text, latency = await call(tier, system, user)
        return {"ok": True, "text": text.strip(), "latency": latency}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "latency": 0.0}


async def main():
    out_path = Path(__file__).parent / "bench_results.md"
    lines: list[str] = ["# Bench results\n"]

    providers = ["nvidia", "openrouter", "yandex"]

    for name, tier, system, user in PROMPTS:
        lines.append(f"## `{name}` ({tier})\n")
        lines.append("**System:**\n```\n" + system + "\n```\n")
        lines.append("**User:**\n```\n" + user + "\n```\n")
        results = await asyncio.gather(
            *(_run_one(p, tier, system, user) for p in providers)
        )
        for provider, r in zip(providers, results):
            nv_model = resolve_model(Model.SMART if tier == "smart" else Model.FAST, provider)
            lines.append(f"### {provider} ({nv_model}) — {r['latency']:.2f}s\n")
            if r["ok"]:
                lines.append(r["text"] + "\n")
            else:
                lines.append(f"**ERROR:** {r['error']}\n")
            lines.append("")
        lines.append("---\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
