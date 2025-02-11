import logging
import re

from aiohttp import ClientSession

from steward.handlers.handler import Handler, validate_command_msg
from steward.helpers.limiter import Duration, check_limit

logger = logging.getLogger(__name__)


# xx or xx/xx ("xx/" part is optional)
# means from_currency/to_currency
NUMBER_REGEX = r"(?P<amount>[0-9]+(\.[0-9]+)?)"
CURRENCY_REGEX = r"(" + NUMBER_REGEX + r")?((?P<from>[a-zA-Z]{3}) (?P<to>[a-zA-Z]{3})"


class ExchangeRateHandler(Handler):
    async def chat(self, update, context):
        assert update.message and update.message.text
        if not validate_command_msg(update, ["exchange"]):
            return False

        # TODO: получать сразу параметры команды из validate_command_msg или ещё одного вызова
        # чтобы не иметь эту логику в хендлерах
        match = re.match(
            r"^/exchange ((?P<amount>[0-9]+(\.[0-9]+)?) )?((?P<from>[a-zA-Z]+) )(?P<to>[a-zA-Z]+)",
            update.message.text,
        )

        if not match:
            await update.message.reply_text(
                "Использование: /exchange [<amount>] <from_currency> <to_currency>"
            )
            return True

        logger.info(match)

        from_currency = match.group("from").upper() if match.group("from") else "BYN"
        to_currency = str(match.group("to")).upper()
        amount = float(match.group("amount")) if match.group("amount") else 1

        logger.info(f"from: {from_currency}, to: {to_currency}, amount: {amount}")

        if from_currency == to_currency:
            await update.message.reply_text(
                f"Валюты {from_currency} и {to_currency} совпадают"
            )
            return True

        check_limit(self, 10, Duration.MINUTE, name=str(update.message.from_user.id))

        async with ClientSession() as session:
            async with session.get(
                "https://api.coinbase.com/v2/exchange-rates",
                params={
                    "currency": from_currency,
                },
            ) as response:
                json = await response.json()

                logger.info(f"got response {json}")

                if (
                    "data" in json
                    and "rates" in json["data"]
                    and len(json["data"]["rates"].keys()) == 1
                ):
                    await update.message.reply_text(
                        f"Валюта {from_currency} не поддерживается"
                    )
                    return True

                rates = json["data"]["rates"]

                if to_currency not in rates:
                    await update.message.reply_text(
                        f"Валюта {to_currency} не поддерживается"
                    )
                    return True

                await update.message.reply_text(
                    f"{amount} {from_currency} = {float(rates[to_currency]) * amount} {to_currency}"
                )

        return True

    def help(self) -> str | None:
        return (
            "/exchange [[<amount> ]<from_currency>/]<to_currency> - конвертация валют"
        )
