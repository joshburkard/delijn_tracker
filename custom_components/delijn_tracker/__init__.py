"""The De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
        self._latest_delays = {}  # Store latest delays per device
        self._last_update_time = {}  # Store when the delay was last updated

    async def _async_update_data(self):
        """Update data via API."""
        try:
            async with async_timeout.timeout(30):
                data = {}
                now = datetime.now()
                today = now.date()

                for device in self.devices:
                    try:
                        halte = device[CONF_HALTE_NUMBER]
                        line = device[CONF_LINE_NUMBER]
                        target_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
                        entity_number = device.get("entity_number")
                        device_id = f"{halte}_{line}_{target_time}"

                        schedule_times = await self.api.get_schedule_times(
                            halte,
                            line,
                            target_time=target_time,
                            entity_number=entity_number
                        )

                        latest_real_time = None
                        latest_delay = None

                        if schedule_times:
                            realtime_data = await self.api.get_realtime_data(
                                halte,
                                line,
                                device[CONF_SCHEDULED_TIME]
                            )

                            # Check for realtime data
                            if realtime_data and realtime_data.get("realtime_time") and realtime_data.get("dienstregelingTijdstip"):
                                real_time = datetime.fromisoformat(realtime_data["realtime_time"].replace('Z', '+00:00'))

                                if real_time.date() == today:
                                    sched_time = datetime.fromisoformat(realtime_data["dienstregelingTijdstip"].replace('Z', '+00:00'))
                                    current_delay = round((real_time - sched_time).total_seconds() / 60)

                                    # Always use the most recent data
                                    latest_real_time = real_time
                                    latest_delay = current_delay

                                    _LOGGER.info(
                                        "New delay data for %s: %d minutes at %s",
                                        device_id,
                                        current_delay,
                                        real_time.strftime("%H:%M:%S")
                                    )

                                    # Update stored values
                                    self._latest_delays[device_id] = current_delay
                                    self._last_update_time[device_id] = real_time

                            data[device_id] = {
                                "schedule": schedule_times,
                                "realtime": realtime_data,
                                "device_info": device,
                                "latest_delay": latest_delay if latest_delay is not None else self._latest_delays.get(device_id, 0),
                                "last_delay_update": latest_real_time or self._last_update_time.get(device_id)
                            }

                    except Exception as err:
                        _LOGGER.error("Error updating device %s: %s", device_id, str(err))
                        data[device_id] = {
                            "schedule": [],
                            "realtime": {},
                            "device_info": device,
                            "latest_delay": self._latest_delays.get(device_id, 0),
                            "last_delay_update": self._last_update_time.get(device_id)
                        }
                        continue

                return data

        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}")
