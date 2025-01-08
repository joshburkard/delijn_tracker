"""Support for De Lijn Bus Tracker sensors."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    CONF_HALTE_NUMBER,
    CONF_LINE_NUMBER,
    CONF_SCHEDULED_TIME,
    CONF_DESTINATION,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="waiting_time",
        name="Waiting Time",
        icon="mdi:clock",
        native_unit_of_measurement="min",
    ),
    SensorEntityDescription(
        key="delay",
        name="Delay",
        icon="mdi:clock-alert",
        native_unit_of_measurement="min",
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up De Lijn Bus Tracker sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug("Setting up sensors for entry: %s", entry.entry_id)
    _LOGGER.debug("Entry data: %s", entry.data)

    entities = []
    devices = entry.data.get("devices", [])
    _LOGGER.debug("Found %d devices to set up", len(devices))

    for device in devices:
        _LOGGER.debug("Creating sensors for device: %s", device)
        for description in SENSOR_TYPES:
            entities.append(
                DeLijnSensor(
                    coordinator=coordinator,
                    entry=entry,
                    device=device,
                    description=description,
                )
            )

    async_add_entities(entities)

class DeLijnSensor(CoordinatorEntity, SensorEntity):
    """Representation of a De Lijn sensor."""

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        device: dict,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._device = device
        _LOGGER.debug("Initializing sensor for device: %s with description: %s", device, description)

        # Set unique ID for each sensor
        self._attr_unique_id = (
            f"{entry.entry_id}_{device[CONF_HALTE_NUMBER]}_{device[CONF_LINE_NUMBER]}_{description.key}"
        )

        # Get scheduled time for device name
        scheduled_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM

        # Format device name
        device_name = (
            f"Halte {device[CONF_HALTE_NUMBER]} - "
            f"Bus {device.get('public_line', device[CONF_LINE_NUMBER])} - "
            f"{device[CONF_DESTINATION]} - "
            f"{scheduled_time}"
        )

        self._attr_name = f"{device_name} {description.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{device[CONF_HALTE_NUMBER]}_{device[CONF_LINE_NUMBER]}")},
            name=device_name,
            manufacturer="De Lijn",
            model=device.get("vehicle_type", "Bus"),
            via_device=(DOMAIN, entry.entry_id),
        )
        _LOGGER.debug("Sensor initialized with name: %s", self._attr_name)

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        try:
            # Get device identifier
            device_id = f"{self._device[CONF_HALTE_NUMBER]}_{self._device[CONF_LINE_NUMBER]}"
            device_data = self.coordinator.data.get(device_id, {})

            if not device_data:
                _LOGGER.debug("No data found for device %s", device_id)
                return None

            # Get newest schedule entry
            schedule = next(iter(device_data.get("schedule", [])), None)
            if not schedule:
                _LOGGER.debug("No schedule found for device %s", device_id)
                return None

            realtime = device_data.get("realtime", {})
            _LOGGER.debug("Processing sensor value with schedule: %s and realtime: %s", schedule, realtime)

            if self.entity_description.key == "waiting_time":
                return schedule.get("waiting_time")
            elif self.entity_description.key == "delay":
                if realtime and realtime.get("realtime_time"):
                    return realtime.get("delay_minutes")

            return None

        except Exception as err:
            _LOGGER.error("Error getting native value: %s", err)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes."""
        if not self.coordinator.data:
            return None

        try:
            # Get device identifier
            device_id = f"{self._device[CONF_HALTE_NUMBER]}_{self._device[CONF_LINE_NUMBER]}"
            device_data = self.coordinator.data.get(device_id, {})

            if not device_data:
                return None

            # Get newest schedule entry
            schedule = next(iter(device_data.get("schedule", [])), None)
            if not schedule:
                return None

            attributes = {
                "scheduled_time": schedule["time"],
                "scheduled_date": schedule.get("date", "Unknown"),
                "destination": schedule["bestemming"],
                "rit_number": schedule["ritnummer"],
                "line_description": schedule.get("line_description"),
                "vehicle_type": schedule.get("vehicle_type"),
                "public_line": schedule.get("public_line"),
            }

            # Add formatted waiting time
            waiting_time = schedule.get("waiting_time")
            if waiting_time is not None and self.entity_description.key == "waiting_time":
                total_minutes = int(waiting_time)
                days = total_minutes // (24 * 60)
                remaining_minutes = total_minutes % (24 * 60)
                hours = remaining_minutes // 60
                mins = remaining_minutes % 60
                attributes["time_formatted"] = f"{days}.{hours:02d}:{mins:02d}"

            realtime = device_data.get("realtime", {})
            if realtime:
                if realtime.get("realtime_time"):
                    attributes["realtime_time"] = realtime["realtime_time"]
                    delay = realtime.get("delay_minutes", 0)
                    attributes["delay_minutes"] = delay

                    # Add status based on delay
                    if delay <= -1:  # Early
                        attributes["status"] = "early"
                        attributes["status_detail"] = f"{abs(delay)} minutes early"
                    elif delay <= 1:  # On time (-1 to +1 minute)
                        attributes["status"] = "on_time"
                        attributes["status_detail"] = "On time"
                    elif delay <= 5:  # Slightly delayed
                        attributes["status"] = "slightly_delayed"
                        attributes["status_detail"] = f"{delay} minutes delayed"
                    else:  # Significantly delayed
                        attributes["status"] = "delayed"
                        attributes["status_detail"] = f"{delay} minutes delayed"

                if realtime.get("prediction_status"):
                    attributes["prediction_status"] = realtime["prediction_status"]

                if realtime.get("vehicle_number"):
                    attributes["vehicle_number"] = realtime["vehicle_number"]

                if realtime.get("direction"):
                    attributes["direction"] = realtime["direction"]

            return attributes

        except Exception as err:
            _LOGGER.error("Error getting attributes: %s", err)
            return None
