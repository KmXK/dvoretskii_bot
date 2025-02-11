import logging
import re
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession
from pyrate_limiter import Callable
from yarl import Query

from steward.handlers.handler import Handler, validate_command_msg
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


# xx or xx/xx ("xx/" part is optional)
# means from_currency/to_currency
NUMBER_REGEX = r"(?P<amount>[0-9]+(\.[0-9]+)?)"
CURRENCY_REGEX = r"(" + NUMBER_REGEX + r")?((?P<from>[a-zA-Z]{3}) (?P<to>[a-zA-Z]{3})"


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


class ExchangeRateHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text
        if not validate_command_msg(update, ["exchange"]):
            return False

        # TODO: получать сразу параметры команды из validate_command_msg или ещё одного вызова
        # чтобы не иметь эту логику в хендлерах
        match = re.match(
            r"^((?P<amount>[0-9]+(\.[0-9]+)?) )?((?P<from>[a-zA-Z]+) )(?P<to>[a-zA-Z]+)",
            " ".join(update.message.text.split(" ")[1:]),
        )

        if not match:
            await update.message.reply_text(
                "Использование: /exchange [<amount>] <from_currency> <to_currency>"
            )
            return True

        logger.info(match)

        from_currency = match.group("from").upper() if match.group("from") else "BYN"
        to_currency = str(match.group("to")).upper()
        amount = float(match.group("amount")) if match.group("amount") else 1.0

        logger.info(f"from: {from_currency}, to: {to_currency}, amount: {amount}")

        if from_currency == to_currency:
            await update.message.reply_text(
                f"Валюты {from_currency} и {to_currency} совпадают"
            )
            return True

        check_limit(self, 10, Duration.MINUTE, name=str(update.message.from_user.id))

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
                await update.message.reply_text(
                    f"{amount} {from_currency} = {rate * amount} {to_currency}"
                )
                return True

        await update.message.reply_text(
            f"Конвертация {from_currency} в {to_currency} невозможна"
        )

        return True

    def help(self) -> str | None:
        return (
            "/exchange [[<amount> ]<from_currency>/]<to_currency> - конвертация валют"
        )
