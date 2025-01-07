# custom_components/delijn_tracker/__init__.py
"""The De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_HALTE_NUMBER,
    CONF_LINE_NUMBER,
    CONF_SCHEDULED_TIME,
    DEFAULT_SCAN_INTERVAL,
)
from .api import DeLijnApi

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up De Lijn Bus Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api = DeLijnApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
    )

    coordinator = DeLijnDataUpdateCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

class DeLijnDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching De Lijn data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DeLijnApi,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self):
        """Fetch data from De Lijn."""
        try:
            async with async_timeout.timeout(30):
                # Get the configured time from the entry
                configured_time = self.entry.data[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM

                # Get schedule data including future days if needed
                schedule_times = await self.api.get_schedule_times(
                    self.entry.data[CONF_HALTE_NUMBER],
                    self.entry.data[CONF_LINE_NUMBER],
                    target_time=configured_time,
                )

                # Get real-time data
                realtime_data = await self.api.get_realtime_data(
                    self.entry.data[CONF_HALTE_NUMBER],
                    self.entry.data[CONF_LINE_NUMBER],
                    self.entry.data[CONF_SCHEDULED_TIME],
                )

                return {
                    "schedule": schedule_times,
                    "realtime": realtime_data,
                }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")
