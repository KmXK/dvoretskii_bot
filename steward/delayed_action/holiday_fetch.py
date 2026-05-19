import datetime
import logging
from dataclasses import dataclass
from os import environ

import aiohttp
from bs4 import BeautifulSoup, Tag

from steward.data.models.holiday_cache import HolidayCache
from steward.delayed_action.base import DelayedAction
from steward.delayed_action.context import DelayedActionContext
from steward.delayed_action.generators.base import Generator
from steward.helpers.class_mark import class_mark

logger = logging.getLogger(__name__)

_SITE_URL = "https://kakoysegodnyaprazdnik.ru/"


def _parse_other_holiday(div: Tag) -> str | None:
    """Extract holiday name from a div.other element."""
    age_el = div.select_one("span.super")
    age = age_el.get_text(strip=True) if age_el else None

    # Build a fresh soup from the div string so we can mutate it safely
    clone = BeautifulSoup(str(div), "html.parser").find("div")
    for tag in clone.find_all("img"):
        tag.decompose()
    for tag in clone.find_all("span", class_="super"):
        tag.decompose()

    text = clone.get_text(" ", strip=True).lstrip("•").strip()
    if not text:
        return None
    return f"{text} ({age})" if age else text


def parse_all_holidays(html: str) -> tuple[list[str], list[str], list[str]]:
    """Parse today's, yesterday's, and tomorrow's holidays from the main page.

    Returns (today_list, yesterday_list, tomorrow_list).
    """
    soup = BeautifulSoup(html, "html.parser")

    # --- Today ---
    today_list: list[str] = []
    for container in soup.select('div[itemtype="http://schema.org/Answer"]'):
        name_el = container.select_one('span[itemprop="text"]')
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        age_el = container.select_one("span.super")
        if age_el:
            name = f"{name} ({age_el.get_text(strip=True)})"
        today_list.append(name)

    # --- Yesterday & Tomorrow from listing_next blocks ---
    yesterday_list: list[str] = []
    tomorrow_list: list[str] = []

    for block in soup.select("div.listing_next"):
        h3 = block.find("h3")
        if not h3:
            continue
        h3_lower = h3.get_text().lower()
        target: list[str] | None = None
        if "вчера" in h3_lower:
            target = yesterday_list
        elif "завтра" in h3_lower:
            target = tomorrow_list

        if target is None:
            continue

        for div in block.select("div.other"):
            holiday = _parse_other_holiday(div)
            if holiday:
                target.append(holiday)

    return today_list, yesterday_list, tomorrow_list


async def fetch_html(session: aiohttp.ClientSession, url: str) -> str | None:
    """Fetch HTML via FlareSolverr if FLARESOLVERR_URL is set, otherwise directly."""
    flaresolverr_url = environ.get("FLARESOLVERR_URL")
    try:
        if flaresolverr_url:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
            async with session.post(
                flaresolverr_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as resp:
                data = await resp.json()
                if data.get("status") != "ok":
                    logger.warning("FlareSolverr error: %s", data.get("message"))
                    return None
                return data["solution"]["response"]
        else:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 300:
                    logger.warning("HTTP %s fetching %s", resp.status, url)
                    return None
                return await resp.text()
    except Exception:
        logger.exception("Failed to fetch %s", url)
        return None


def _has_cache(repo, date_str: str) -> bool:
    return any(c.date == date_str for c in repo.db.holiday_caches)


def _upsert_cache(repo, date_str: str, holidays: list[str]):
    repo.db.holiday_caches = [c for c in repo.db.holiday_caches if c.date != date_str]
    repo.db.holiday_caches.append(HolidayCache(date=date_str, holidays=holidays))


@dataclass
@class_mark("generator/holiday_fetch")
class HolidayFetchGenerator(Generator):
    next_fire: datetime.datetime
    interval_days: int = 3

    def get_next(self, now: datetime.datetime) -> datetime.datetime:
        if self.next_fire.tzinfo is None:
            self.next_fire = self.next_fire.replace(tzinfo=datetime.timezone.utc)
        return self.next_fire


@dataclass
@class_mark("delayed_action/holiday_fetch")
class HolidayFetchAction(DelayedAction):
    generator: HolidayFetchGenerator

    async def execute(self, context: DelayedActionContext):
        repo = context.repository
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        tomorrow = today + datetime.timedelta(days=1)

        logger.info("Holiday fetch starting for %s (interval=%dd)", today, self.generator.interval_days)

        async with aiohttp.ClientSession() as session:
            html = await fetch_html(session, _SITE_URL)

        if not html:
            logger.warning("Holiday fetch: page unavailable, retrying in 1 day")
            self.generator.next_fire = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
            )
            await repo.save()
            return

        today_list, yesterday_list, tomorrow_list = parse_all_holidays(html)

        if not today_list:
            logger.warning(
                "Holiday fetch: parsed 0 holidays for today from %s — "
                "site structure may have changed. HTML snippet: %.500s",
                _SITE_URL,
                html,
            )

        saved = 0
        for date_obj, holidays in [
            (today, today_list),
            (yesterday, yesterday_list),
            (tomorrow, tomorrow_list),
        ]:
            if holidays:
                _upsert_cache(repo, date_obj.isoformat(), holidays)
                saved += 1
                logger.info("Holiday fetch: cached %d holidays for %s", len(holidays), date_obj)
            else:
                logger.debug("Holiday fetch: no holidays parsed for %s", date_obj)

        if not saved:
            logger.warning("Holiday fetch: nothing was cached (all lists empty)")
        else:
            # Keep only last 30 days in cache
            cutoff = (today - datetime.timedelta(days=30)).isoformat()
            repo.db.holiday_caches = [c for c in repo.db.holiday_caches if c.date >= cutoff]

        next_fire = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=self.generator.interval_days)
        )
        self.generator.next_fire = next_fire
        logger.info("Holiday fetch done, next run at %s", next_fire.strftime("%Y-%m-%d %H:%M UTC"))
        await repo.save()


def ensure_holiday_fetch_scheduled(repo) -> bool:
    """Create the periodic holiday fetch action if not already present. Returns True if created."""
    if any(isinstance(a, HolidayFetchAction) for a in repo.db.delayed_actions):
        return False
    repo.db.delayed_actions.append(
        HolidayFetchAction(
            generator=HolidayFetchGenerator(
                next_fire=datetime.datetime.now(datetime.timezone.utc),
                interval_days=3,
            )
        )
    )
    return True
