"""The De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import async_timeout

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

    _LOGGER.debug("Setting up De Lijn integration with entry: %s", entry.entry_id)
    _LOGGER.debug("Entry data: %s", entry.data)

    api = DeLijnApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
    )

    coordinator = DeLijnDataUpdateCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(
        entry.add_update_listener(update_listener)
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

class DeLijnDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching De Lijn data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DeLijnApi,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.entry = entry
        self.devices = entry.data.get("devices", [])

    async def _async_update_data(self):
        """Update data via API."""
        try:
            async with async_timeout.timeout(30):
                data = {}

                for device in self.devices:
                    try:
                        halte = device[CONF_HALTE_NUMBER]
                        line = device[CONF_LINE_NUMBER]
                        target_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
                        entity_number = device.get("entity_number")

                        # Create unique device identifier including the time
                        device_id = f"{halte}_{line}_{target_time}"

                        _LOGGER.info(
                            "Fetching data for halte %s, line %s, time %s",
                            halte, line, target_time
                        )

                        schedule_times = await self.api.get_schedule_times(
                            halte,
                            line,
                            target_time=target_time,
                            entity_number=entity_number
                        )

                        if schedule_times:
                            realtime_data = await self.api.get_realtime_data(
                                halte,
                                line,
                                device[CONF_SCHEDULED_TIME]
                            )

                            data[device_id] = {
                                "schedule": schedule_times,
                                "realtime": realtime_data,
                                "device_info": device
                            }
                            _LOGGER.debug("Updated data for device %s", device_id)
                        else:
                            _LOGGER.info(
                                "No schedule times found for halte %s, line %s, time %s",
                                halte, line, target_time
                            )

                    except Exception as err:
                        _LOGGER.error(
                            "Error updating device %s: %s",
                            device_id,
                            str(err)
                        )
                        continue

                return data

        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}")
