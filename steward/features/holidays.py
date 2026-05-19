import logging
from datetime import date

import aiohttp

from steward.delayed_action.holiday_fetch import (
    HolidayFetchAction,
    _upsert_cache,
    ensure_holiday_fetch_scheduled,
    fetch_html,
    parse_all_holidays,
)
from steward.framework import Feature, FeatureContext, subcommand
from steward.helpers.formats import format_lined_list

logger = logging.getLogger(__name__)

_SITE_URL = "https://kakoysegodnyaprazdnik.ru/"


class HolidaysFeature(Feature):
    command = "holidays"
    description = "Какие сегодня праздники"

    async def init(self):
        if ensure_holiday_fetch_scheduled(self.repository):
            await self.repository.save()
            logger.info("Scheduled holiday fetch action")

    @subcommand("", description="Праздники сегодня")
    async def show(self, ctx: FeatureContext):
        today = date.today().isoformat()
        cache_entry = next(
            (c for c in self.repository.db.holiday_caches if c.date == today),
            None,
        )

        if cache_entry and cache_entry.holidays:
            holidays = list(enumerate(cache_entry.holidays, start=1))
            await ctx.reply("\n".join(["Праздники сегодня:", format_lined_list(holidays)]))
            return

        await ctx.reply("⏳ Загружаю праздники...")
        async with aiohttp.ClientSession() as session:
            html = await fetch_html(session, _SITE_URL)

        if not html:
            await ctx.reply("Не удалось загрузить праздники (Cloudflare или сеть)")
            return

        today_list, yesterday_list, tomorrow_list = parse_all_holidays(html)

        # Persist everything we got
        from datetime import timedelta
        today_date = date.today()
        for date_obj, holidays in [
            (today_date, today_list),
            (today_date - timedelta(days=1), yesterday_list),
            (today_date + timedelta(days=1), tomorrow_list),
        ]:
            if holidays:
                _upsert_cache(self.repository, date_obj.isoformat(), holidays)
        await self.repository.save()

        if not today_list:
            await ctx.reply("Праздники не найдены на странице")
            return

        holidays = list(enumerate(today_list, start=1))
        await ctx.reply("\n".join(["Праздники сегодня:", format_lined_list(holidays)]))

    @subcommand("refresh", description="Принудительно обновить праздники")
    async def refresh(self, ctx: FeatureContext):
        action = next(
            (a for a in self.repository.db.delayed_actions if isinstance(a, HolidayFetchAction)),
            None,
        )
        if action is None:
            await ctx.reply("Задача обновления не найдена")
            return
        from datetime import datetime, timezone
        action.generator.next_fire = datetime.now(timezone.utc)
        await self.repository.save()
        await ctx.reply("✅ Запланировано обновление — данные появятся через ~минуту")
