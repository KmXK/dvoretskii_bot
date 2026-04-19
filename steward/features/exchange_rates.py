import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from aiohttp import ClientSession
from yarl import Query

from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.command_validation import ValidationArgumentsError
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


_PATTERN = re.compile(
    r"((?P<amount>[0-9]+(\.[0-9]+)?) )?((?P<from_currency>[a-zA-Z]+) )?(?P<to_currency>[a-zA-Z]+)"
)


@dataclass
class _ApiData:
    api: str
    params: Query
    get_func: Callable[[dict], Any]

    async def fetch(self) -> float | None:
        async with ClientSession() as session:
            async with session.get(self.api, params=self.params) as response:
                data = await response.json()
                try:
                    return float(self.get_func(data))
                except Exception:
                    return None


class ExchangeRateFeature(Feature):
    command = "exchange"
    description = "Конвертация валют"
    help_examples = [
        "«сколько 200 долларов в рублях» → /exchange 200 USD RUB",
        "«курс евро» → /exchange EUR",
        "«100 евро в долларах» → /exchange 100 EUR USD",
        "«курс биткоина в долларах» → /exchange BTC USD",
    ]

    @subcommand(_PATTERN, description="[<сумма>] [<из>] <в>")
    async def convert(self, ctx: FeatureContext, **kw):
        amount_raw = kw.get("amount")
        from_raw = kw.get("from_currency")
        to_raw = kw.get("to_currency")
        if to_raw is None:
            raise ValidationArgumentsError()

        amount = float(amount_raw) if amount_raw else 1.0
        from_currency = (from_raw or "BYN").upper()
        to_currency = to_raw.upper()

        if from_currency == to_currency:
            await ctx.reply(f"Валюты {from_currency} и {to_currency} совпадают")
            return

        check_limit(self, 10, Duration.MINUTE, name=str(ctx.user_id))

        apis = [
            _ApiData(
                api="https://api.coinbase.com/v2/exchange-rates",
                params={"currency": from_currency},
                get_func=lambda j: j["data"]["rates"][to_currency],
            ),
            _ApiData(
                api="https://data-api.binance.vision/api/v3/avgPrice",
                params={
                    "symbol": f"{'USDT' if from_currency == 'USD' else from_currency}"
                    f"{'USDT' if to_currency == 'USD' else to_currency}"
                },
                get_func=lambda j: j["price"],
            ),
        ]

        for api in apis:
            rate = await api.fetch()
            if rate:
                await ctx.reply(
                    f"{amount} {from_currency} = {rate * amount} {to_currency}"
                )
                return

        await ctx.reply(f"Конвертация {from_currency} в {to_currency} невозможна")
