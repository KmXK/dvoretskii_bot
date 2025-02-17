import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession
from pyrate_limiter import Callable
from yarl import Query

from steward.bot.context import ChatBotContext
from steward.handlers.command_handler import CommandHandler, required
from steward.handlers.handler import Handler
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


@dataclass
class ApiData:
    api: str
    params: Query
    get_func: Callable[[dict], Any]

    async def try_get_exchange_rate(self) -> float | None:
        logger.info(f"using endpoint: {self.api}")
        async with ClientSession() as session:
            async with session.get(
                self.api,
                params=self.params,
            ) as response:
                json = await response.json()

                logger.info(f"got response {json}")

                try:
                    return float(self.get_func(json))
                except Exception as _:
                    return None


@CommandHandler(
    "exchange",
    arguments_template=r"((?P<amount>[0-9]+(\.[0-9]+)?) )?((?P<from_currency>[a-zA-Z]+) )?(?P<to_currency>[a-zA-Z]+)",
    arguments_mapping={
        "amount": lambda x: float(x or 1),
        "from_currency": lambda x: (x or "BYN").upper(),
        "to_currency": required(str.upper),
    },
)
class ExchangeRateHandler(Handler):
    async def chat(
        self,
        context: ChatBotContext,
        to_currency: str,
        amount: float,
        from_currency: str,
    ):
        assert context.message and context.message.text

        logger.info(f"from: {from_currency}, to: {to_currency}, amount: {amount}")

        if from_currency == to_currency:
            await context.message.reply_text(
                f"Валюты {from_currency} и {to_currency} совпадают"
            )
            return True

        check_limit(self, 10, Duration.MINUTE, name=str(context.message.from_user.id))

        apis = [
            ApiData(
                api="https://api.coinbase.com/v2/exchange-rates",
                params={
                    "currency": from_currency,
                },
                get_func=lambda json: json["data"]["rates"][to_currency],
            ),
            ApiData(
                api="https://data-api.binance.vision/api/v3/avgPrice",
                params={
                    "symbol": f"{'USDT' if from_currency == 'USD' else from_currency}{'USDT' if to_currency == 'USD' else to_currency}",
                },
                get_func=lambda json: json["price"],
            ),
        ]

        for api in apis:
            rate = await api.try_get_exchange_rate()

            if rate:
                await context.message.reply_text(
                    f"{amount} {from_currency} = {rate * float(amount or 1.0)} {to_currency}"
                )
                return True

        await context.message.reply_text(
            f"Конвертация {from_currency} в {to_currency} невозможна"
        )

        return True

    def help(self) -> str | None:
        return (
            "/exchange [[<amount> ]<from_currency>/]<to_currency> - конвертация валют"
        )
