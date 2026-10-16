"""TCAT (Troyes) next buses: one config entry per favourite stop."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .tcat import GTFS_URL, TRIP_UPDATES_URL, Departure, Gtfs, departures, parse_trip_updates

DOMAIN = "tcat"
PLATFORMS = [Platform.SENSOR]
CONF_ROUTE, CONF_STOP, CONF_WALK = "route", "stop", "walk"
_LOGGER = logging.getLogger(__name__)
type TcatConfigEntry = ConfigEntry[TcatCoordinator]


class TcatData:
    """Timetable and live feed, shared by every favourite."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.session = async_get_clientsession(hass)
        self.gtfs: Gtfs | None = None
        self.gtfs_due = 0.0
        self.live: dict = {}
        self.live_at = 0.0
        self.lock = asyncio.Lock()

    async def _get(self, url: str) -> bytes:
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
            r.raise_for_status()
            return await r.read()

    async def timetable(self) -> Gtfs:
        async with self.lock:
            now = self.hass.loop.time()
            if now >= self.gtfs_due:  # TCAT publishes a new timetable every few weeks
                try:
                    self.gtfs = await self.hass.async_add_executor_job(Gtfs, await self._get(GTFS_URL))
                    self.gtfs_due = now + 6 * 3600
                except Exception as err:  # keep the previous timetable rather than nothing
                    self.gtfs_due = now + 600
                    if self.gtfs is None:
                        raise UpdateFailed(f"TCAT timetable unavailable: {err}") from err
                    _LOGGER.warning("TCAT timetable not refreshed: %s", err)
            return self.gtfs

    async def realtime(self) -> dict:
        async with self.lock:
            if self.hass.loop.time() - self.live_at > 20:  # several favourites refreshing together share one fetch
                try:
                    self.live = parse_trip_updates(await self._get(TRIP_UPDATES_URL))
                except Exception as err:  # the timetable alone is still useful
                    _LOGGER.debug("TCAT live feed unavailable: %s", err)
                    self.live = {}
                self.live_at = self.hass.loop.time()
            return self.live


def tcat_data(hass: HomeAssistant) -> TcatData:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = TcatData(hass)
    return hass.data[DOMAIN]


class TcatCoordinator(DataUpdateCoordinator[list[Departure]]):
    def __init__(self, hass: HomeAssistant, entry: TcatConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title, update_interval=timedelta(seconds=30))
        self.shared = tcat_data(hass)
        self.gtfs: Gtfs | None = None
        self.runs = []

    async def _async_update_data(self) -> list[Departure]:
        gtfs = await self.shared.timetable()
        if gtfs is not self.gtfs:
            route, stop = self.config_entry.data[CONF_ROUTE], self.config_entry.data[CONF_STOP]
            self.runs = await self.hass.async_add_executor_job(gtfs.runs, route, stop)
            self.gtfs = gtfs
            if not self.runs:
                _LOGGER.warning("%s: no bus in the current TCAT timetable", self.config_entry.title)
        live = await self.shared.realtime()
        return departures(gtfs, self.runs, live, dt_util.utcnow(), int(self.config_entry.options.get(CONF_WALK, 0)))


async def async_setup_entry(hass: HomeAssistant, entry: TcatConfigEntry) -> bool:
    coordinator = TcatCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TcatConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
