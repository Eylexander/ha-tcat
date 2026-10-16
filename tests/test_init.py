"""The integration inside Home Assistant: pip install pytest-homeassistant-custom-component && python -m pytest tests"""
from datetime import datetime

import pytest
from feed import gtfs_zip, trip_updates

from custom_components.tcat.tcat import GTFS_URL, TRIP_UPDATES_URL, TZ
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_favourite(hass, aioclient_mock, freezer):
    freezer.move_to(datetime(2026, 10, 16, 7, 55, tzinfo=TZ))
    aioclient_mock.get(GTFS_URL, content=gtfs_zip())
    aioclient_mock.get(TRIP_UPDATES_URL, content=trip_updates(("T1", False, [(2, False, None, 120)])))

    r = await hass.config_entries.flow.async_init("tcat", context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"route": "R1"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "stop"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"stop": "BETA|0", "walk": 0})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["title"] == "1 · BETA → ÉGLISE"
    await hass.async_block_till_done()
    entry = r["result"]

    reg = er.async_get(hass)
    next_bus = hass.states.get(reg.async_get_entity_id("sensor", "tcat", f"{entry.entry_id}_next"))
    minutes = reg.async_get_entity_id("sensor", "tcat", f"{entry.entry_id}_minutes")
    assert datetime.fromisoformat(next_bus.state) == datetime(2026, 10, 16, 8, 12, tzinfo=TZ)
    assert next_bus.attributes["realtime"] and next_bus.attributes["delay"] == 2
    assert next_bus.attributes["line"] == "1" and next_bus.attributes["line_color"] == "#F29400"
    assert hass.states.get(minutes).state == "17"
    assert aioclient_mock.call_count == 2  # one timetable download shared by the flow and the entry

    # Walking 20 min: the 08:12 bus is out of reach.
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"walk": 20})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(minutes).state == "45"

    # Same favourite twice is refused.
    r = await hass.config_entries.flow.async_init("tcat", context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"route": "R1"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"stop": "BETA|0", "walk": 0})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "already_configured"
