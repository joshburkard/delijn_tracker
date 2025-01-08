# custom_components/delijn_tracker/__init__.py

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

    _LOGGER.debug("Setting up De Lijn entry with data: %s", entry.data)

    # Create API instance
    api = DeLijnApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
    )

    # Create coordinator
    coordinator = DeLijnDataUpdateCoordinator(hass, api, entry)

    # Do first refresh
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener
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
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.entry = entry
        _LOGGER.debug("Initialized coordinator with entry data: %s", entry.data)

    async def _async_update_data(self):
        """Fetch data from De Lijn."""
        try:
            async with async_timeout.timeout(30):
                data = {}

                _LOGGER.debug("Starting data update for entry: %s", self.entry.entry_id)
                devices = self.entry.data.get("devices", [])
                _LOGGER.debug("Found %d devices to update", len(devices))

                # Fetch data for each device
                for device in devices:
                    try:
                        device_id = f"{device[CONF_HALTE_NUMBER]}_{device[CONF_LINE_NUMBER]}"
                        _LOGGER.debug("Processing device %s", device_id)

                        # Get schedule data for current/future times with specified target time
                        schedule_times = await self.api.get_schedule_times(
                            device[CONF_HALTE_NUMBER],
                            device[CONF_LINE_NUMBER],
                            target_time=device[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM
                        )
                        _LOGGER.debug("Got schedule times: %s", schedule_times)

                        # Get real-time data if available
                        realtime_data = {}
                        if schedule_times:
                            next_departure = schedule_times[0]
                            realtime_data = await self.api.get_realtime_data(
                                device[CONF_HALTE_NUMBER],
                                device[CONF_LINE_NUMBER],
                                device[CONF_SCHEDULED_TIME]
                            )
                            _LOGGER.debug("Got realtime data: %s", realtime_data)

                            # Calculate delay if realtime data is available
                            if realtime_data and realtime_data.get("realtime_time"):
                                real_time = datetime.fromisoformat(realtime_data["realtime_time"].replace('Z', '+00:00'))
                                sched_time = datetime.fromisoformat(realtime_data["dienstregelingTijdstip"].replace('Z', '+00:00'))
                                delay = round((real_time - sched_time).total_seconds() / 60)
                                realtime_data["delay_minutes"] = delay

                        data[device_id] = {
                            "schedule": schedule_times,
                            "realtime": realtime_data,
                        }
                        _LOGGER.debug("Updated data for device %s: %s", device_id, data[device_id])

                    except Exception as err:
                        _LOGGER.error("Error updating device %s: %s", device_id, err)
                        # Continue with other devices if one fails
                        continue

                _LOGGER.debug("Completed data update with data: %s", data)
                return data

        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err, exc_info=True)
            raise UpdateFailed(f"Error communicating with API: {err}")
