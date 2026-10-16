from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import CONF_ROUTE, DOMAIN, TcatConfigEntry, TcatCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: TcatConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([NextBus(entry.runtime_data, "next"), NextBus(entry.runtime_data, "minutes")])


class NextBus(CoordinatorEntity[TcatCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = "Données TCAT / Troyes Champagne Métropole, Licence Ouverte"

    def __init__(self, coordinator: TcatCoordinator, kind: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.kind = kind
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        if kind == "next":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        else:
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
            self._attr_icon = "mdi:bus-clock"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=f"TCAT {entry.title}",
                                            manufacturer="TCAT", entry_type=DeviceEntryType.SERVICE)

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        when = self.coordinator.data[0].time
        if self.kind == "next":  # to the minute: real-time estimates move by seconds every poll, flooding the logbook
            return (when + timedelta(seconds=30)).replace(second=0, microsecond=0)
        return max(0, int((when - dt_util.utcnow()).total_seconds() // 60))

    @property
    def extra_state_attributes(self):
        if self.kind != "next":
            return None
        deps = self.coordinator.data or []
        route = self.coordinator.gtfs.routes.get(self.coordinator.config_entry.data[CONF_ROUTE], {})
        first = deps[0] if deps else None
        return {
            "line": route.get("route_short_name"),
            "line_color": f'#{route["route_color"]}' if route.get("route_color") else None,
            "terminus": first and first.terminus,
            "realtime": first and first.realtime,
            "delay": round(first.delay / 60) if first and first.delay is not None else None,  # minutes
            "upcoming": [{"time": d.time.isoformat(), "terminus": d.terminus, "realtime": d.realtime} for d in deps[1:]],
        }
