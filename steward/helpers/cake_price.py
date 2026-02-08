import logging
import time
from dataclasses import dataclass

from aiohttp import ClientSession

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
CACHE_TTL = 60


@dataclass
class CakeStatus:
    price: float
    change_1m_pct: float | None
    change_24h_pct: float

    def format(self) -> str:
        m1 = _fmt(self.change_1m_pct)
        d1 = _fmt(self.change_24h_pct)
        return f"🥞CAKE ${self.price:.2f} {m1}|{d1}"


def _fmt(val: float | None) -> str:
    if val is None:
        return "⚪—"
    if val > 0:
        return f"🟢+{val:.1f}%"
    if val < 0:
        return f"🔴{val:.1f}%"
    return "⚪0%"


class CakePriceFetcher:
    def __init__(self):
        self._prev_price: float | None = None
        self._last_fetch: float = 0
        self._cached: CakeStatus | None = None

    async def get_status(self) -> CakeStatus | None:
        now = time.monotonic()
        if self._cached and (now - self._last_fetch) < CACHE_TTL:
            return self._cached

        try:
            async with ClientSession() as session:
                async with session.get(
                    COINGECKO_URL,
                    params={
                        "ids": "pancakeswap-token",
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                    },
                ) as resp:
                    data = await resp.json()

            cake = data.get("pancakeswap-token", {})
            price = cake.get("usd")
            change_24h = cake.get("usd_24h_change")

            if price is None:
                return self._cached

            change_1m = None
            if self._prev_price is not None:
                change_1m = ((price - self._prev_price) / self._prev_price) * 100

            self._prev_price = price
            self._last_fetch = now
            self._cached = CakeStatus(
                price=price,
                change_1m_pct=change_1m,
                change_24h_pct=change_24h or 0.0,
            )
            return self._cached
        except Exception as e:
            logger.warning(f"Failed to fetch CAKE price: {e}")
            return self._cached


cake_fetcher = CakePriceFetcher()
