from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector, NumberSelectorConfig, NumberSelectorMode, SelectOptionDict, SelectSelector,
    SelectSelectorConfig, SelectSelectorMode,
)

from . import CONF_ROUTE, CONF_STOP, CONF_WALK, DOMAIN, tcat_data

_LOGGER = logging.getLogger(__name__)
WALK = NumberSelector(NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="min", mode=NumberSelectorMode.BOX))


def _select(options: dict[str, str]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=[SelectOptionDict(value=k, label=v) for k, v in options.items()],
                                               mode=SelectSelectorMode.DROPDOWN, sort=False))


class TcatConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self.gtfs = None
        self.route = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        try:
            self.gtfs = await tcat_data(self.hass).timetable()
        except Exception:
            _LOGGER.exception("TCAT timetable unavailable")
            return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            self.route = user_input[CONF_ROUTE]
            return await self.async_step_stop()
        return self.async_show_form(step_id="user", data_schema=vol.Schema(
            {vol.Required(CONF_ROUTE): _select(self.gtfs.lines())}))

    async def async_step_stop(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        stops = await self.hass.async_add_executor_job(self.gtfs.stops_of, self.route)
        if user_input is not None:
            stop = user_input[CONF_STOP]
            await self.async_set_unique_id(f"{self.route}|{stop}")
            self._abort_if_unique_id_configured()
            line = self.gtfs.routes[self.route]["route_short_name"]
            title = f"{line} · {stops[stop].split(' / ')[0]}"  # main terminus only: it names the entity ids
            return self.async_create_entry(title=title, data={CONF_ROUTE: self.route, CONF_STOP: stop},
                                           options={CONF_WALK: user_input[CONF_WALK]})
        return self.async_show_form(step_id="stop", data_schema=vol.Schema({
            vol.Required(CONF_STOP): _select(stops),
            vol.Required(CONF_WALK, default=0): WALK,
        }), description_placeholders={"line": self.gtfs.lines()[self.route]})

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return TcatOptionsFlow()


class TcatOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_WALK, default=self.config_entry.options.get(CONF_WALK, 0)): WALK}))
