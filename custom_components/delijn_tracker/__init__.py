"""The De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
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
    DELAY_HIGH, DELAY_MEDIUM, DELAY_LOW,
    EARLY_HIGH, EARLY_MEDIUM, EARLY_LOW,
)
from .api import DeLijnApi

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]

# Storage constants
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.stats"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the De Lijn Bus Tracker component."""
    hass.data.setdefault(DOMAIN, {})
    return True

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

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

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
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._latest_delays = {}  # Store latest delays per device and day
        self._delay_stats = {}  # Store delay statistics per device
        self._last_update_time = {}  # Store when the delay was last updated

    async def _async_initialize_storage(self) -> None:
        """Initialize the storage."""
        stored_data = await self._store.async_load()

        if stored_data:
            self._delay_stats = stored_data.get("delay_stats", {})
            self._latest_delays = stored_data.get("latest_delays", {})
            self._last_update_time = stored_data.get("last_update_time", {})

    async def _async_save_data(self) -> None:
        """Save data to storage."""
        try:
            await self._store.async_save({
                "delay_stats": self._delay_stats,
                "latest_delays": self._latest_delays,
                "last_update_time": self._last_update_time,
            })
        except Exception as err:
            _LOGGER.error("Error saving stats data: %s", err)

    def _update_delay_stats(self, device_id: str, delay: float | None, had_realtime: bool, realtime_time: datetime | None = None) -> None:
        """Update delay statistics for a device."""
        today = datetime.now().date()

        if device_id not in self._delay_stats:
            self._delay_stats[device_id] = {
                "delay_counter": 0,
                "high_delay": 0,
                "medium_delay": 0,
                "low_delay": 0,
                "high_early": 0,
                "medium_early": 0,
                "low_early": 0,
                "last_delay": None,
                "last_delay_date": None,
                "last_had_realtime": True,
            }

        stats = self._delay_stats[device_id]

        # Update delay counter when realtime data becomes unavailable
        if (stats["last_delay"] is not None and
            stats["last_delay"] > DELAY_LOW and
            stats["last_had_realtime"] and
            not had_realtime):
            stats["delay_counter"] += 1

        # Update delay categories if we have a current delay value
        if delay is not None:
            if delay > DELAY_HIGH:  # High delay
                stats["high_delay"] += 1
                _LOGGER.debug("Incrementing high delay counter for %s to %d", device_id, stats["high_delay"])
            elif delay > DELAY_MEDIUM:  # Medium delay
                stats["medium_delay"] += 1
                _LOGGER.debug("Incrementing medium delay counter for %s to %d", device_id, stats["medium_delay"])
            elif delay > DELAY_LOW:  # Low delay
                stats["low_delay"] += 1
                _LOGGER.debug("Incrementing low delay counter for %s to %d", device_id, stats["low_delay"])
            elif delay < -EARLY_HIGH:  # High early
                stats["high_early"] += 1
                _LOGGER.debug("Incrementing high early counter for %s to %d", device_id, stats["high_early"])
            elif delay < -EARLY_MEDIUM:  # Medium early
                stats["medium_early"] += 1
                _LOGGER.debug("Incrementing medium early counter for %s to %d", device_id, stats["medium_early"])
            elif delay < -EARLY_LOW:  # Low early
                stats["low_early"] += 1
                _LOGGER.debug("Incrementing low early counter for %s to %d", device_id, stats["low_early"])

        # Store current state for next comparison
        if delay is not None:
            stats["last_delay"] = delay
            stats["last_delay_date"] = today.isoformat()
        stats["last_had_realtime"] = had_realtime

        # Save after updates
        self.hass.async_create_task(self._async_save_data())

    async def _async_update_data(self):
        """Update data via API."""
        # Initialize storage on first update if not done
        if not self._delay_stats:
            await self._async_initialize_storage()

        try:
            async with async_timeout.timeout(30):
                data = {}
                now = datetime.now()
                today = now.date()
                today_str = today.isoformat()

                for device in self.devices:
                    try:
                        halte = device[CONF_HALTE_NUMBER]
                        line = device[CONF_LINE_NUMBER]
                        target_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
                        entity_number = device.get("entity_number")
                        device_id = f"{halte}_{line}_{target_time}"

                        # Initialize delay storage for today if not exists
                        device_delays = self._latest_delays.setdefault(device_id, {})

                        schedule_times = await self.api.get_schedule_times(
                            halte,
                            line,
                            target_time=target_time,
                            entity_number=entity_number
                        )

                        latest_real_time = None
                        latest_delay = None
                        had_realtime = False

                        if schedule_times:
                            realtime_data = await self.api.get_realtime_data(
                                halte,
                                line,
                                device[CONF_SCHEDULED_TIME]
                            )

                            # Check for realtime data
                            if realtime_data and realtime_data.get("realtime_time") and realtime_data.get("dienstregelingTijdstip"):
                                had_realtime = True
                                real_time = datetime.fromisoformat(realtime_data["realtime_time"].replace('Z', '+00:00'))

                                if real_time.date() == today:
                                    sched_time = datetime.fromisoformat(realtime_data["dienstregelingTijdstip"].replace('Z', '+00:00'))
                                    current_delay = round((real_time - sched_time).total_seconds() / 60)

                                    # Always use the most recent data
                                    latest_real_time = real_time
                                    latest_delay = current_delay

                                    # Store delay for today
                                    device_delays[today_str] = {
                                        'delay': current_delay,
                                        'timestamp': real_time.isoformat()
                                    }

                            # Update delay statistics
                            self._update_delay_stats(device_id, latest_delay, had_realtime, latest_real_time)

                            # Clean up old delay data
                            old_dates = [date for date in device_delays.keys()
                                       if datetime.fromisoformat(date).date() < today]
                            for date in old_dates:
                                del device_delays[date]

                            # Get stored delay stats
                            stored_stats = self._delay_stats.get(device_id, {})

                            data[device_id] = {
                                "schedule": schedule_times,
                                "realtime": realtime_data,
                                "device_info": device,
                                "latest_delay": latest_delay,
                                "last_delay_update": latest_real_time,
                                "stored_delay": device_delays.get(today_str),
                                "delay_stats": stored_stats,
                                "last_known_delay": stored_stats.get("last_delay"),
                                "last_delay_date": stored_stats.get("last_delay_date"),
                            }

                    except Exception as err:
                        _LOGGER.error("Error updating device %s: %s", device_id, str(err))
                        # Still provide stored stats even on error
                        if device_id in self._delay_stats:
                            data[device_id] = {
                                "schedule": [],
                                "realtime": {},
                                "device_info": device,
                                "latest_delay": None,
                                "last_delay_update": None,
                                "stored_delay": self._latest_delays.get(device_id, {}).get(today_str),
                                "delay_stats": self._delay_stats[device_id],
                                "last_known_delay": self._delay_stats[device_id].get("last_delay"),
                                "last_delay_date": self._delay_stats[device_id].get("last_delay_date"),
                            }
                        continue

                return data

        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}")
