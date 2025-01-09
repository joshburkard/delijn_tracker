"""Support for De Lijn Bus Tracker sensors."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
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
        native_unit_of_measurement=None,
    ),
    SensorEntityDescription(
        key="delay",
        name="Delay",
        icon="mdi:clock-alert",
        native_unit_of_measurement="min",
    ),
)

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

        # Create a unique device identifier
        device_unique_id = (
            f"{device[CONF_HALTE_NUMBER]}_"
            f"{device[CONF_LINE_NUMBER]}_"
            f"{device[CONF_SCHEDULED_TIME].split('T')[1][:5]}"
        )

        # Set unique ID for sensor
        self._attr_unique_id = f"{entry.entry_id}_{device_unique_id}_{description.key}"

        # Get the line number
        line_number = device.get("public_line") or device[CONF_LINE_NUMBER]
        scheduled_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
        vehicle_type = device.get("vehicle_type", "Bus").upper()

        # Create device name
        device_name = (
            f"Halte {device[CONF_HALTE_NUMBER]} - "
            f"{vehicle_type} {line_number} - "
            f"{device[CONF_DESTINATION]} - "
            f"{scheduled_time}"
        )

        self._attr_name = f"{device_name} {description.name}"

        # Set device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{device_unique_id}")},
            name=device_name,
            manufacturer="De Lijn",
            model=device.get("vehicle_type", "Bus"),
        )

    @property
    def native_value(self) -> str | int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        try:
            device_id = f"{self._device[CONF_HALTE_NUMBER]}_{self._device[CONF_LINE_NUMBER]}"
            device_data = self.coordinator.data.get(device_id, {})

            if not device_data:
                return None

            scheduled_time = self._device[CONF_SCHEDULED_TIME].split("T")[1][:5]
            schedule = next(
                (time for time in device_data.get("schedule", [])
                 if time["time"] == scheduled_time),
                None
            )

            if not schedule:
                return None

            if self.entity_description.key == "waiting_time":
                now = datetime.now()
                realtime = device_data.get("realtime", {})

                # Check for realtime data
                if realtime and realtime.get("realtime_time"):
                    # Use realtime prediction
                    target_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))

                    # If the realtime prediction is in the past, show "00:00"
                    if target_time < now:
                        return "00:00"
                else:
                    # Use scheduled time
                    target_time = datetime.fromisoformat(schedule["timestamp"].replace('Z', '+00:00'))

                    # For scheduled times, increment to next day if in the past
                    while target_time < now:
                        target_time = target_time + timedelta(days=1)

                # Calculate waiting time
                time_diff = target_time - now
                total_minutes = int(time_diff.total_seconds() / 60)
                days = total_minutes // (24 * 60)
                remaining_minutes = total_minutes % (24 * 60)
                hours = remaining_minutes // 60
                mins = remaining_minutes % 60

                if days > 0:
                    return f"{days} days {hours:02d}:{mins:02d}"
                else:
                    return f"{hours:02d}:{mins:02d}"

            elif self.entity_description.key == "delay":
                realtime = device_data.get("realtime", {})
                if realtime and realtime.get("realtime_time"):
                    real_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                    sched_time = datetime.fromisoformat(realtime["dienstregelingTijdstip"].replace('Z', '+00:00'))
                    return round((real_time - sched_time).total_seconds() / 60)

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
            device_id = f"{self._device[CONF_HALTE_NUMBER]}_{self._device[CONF_LINE_NUMBER]}"
            device_data = self.coordinator.data.get(device_id, {})

            if not device_data:
                return None

            schedule = next(iter(device_data.get("schedule", [])), None)
            if not schedule:
                return None

            attributes = {
                "scheduled_time": schedule["time"],
                "scheduled_date": schedule.get("date", "Unknown"),
                "destination": schedule["bestemming"],
                "rit_number": schedule["ritnummer"],
                "line_description": self._device.get("line_description"),
                "vehicle_type": self._device.get("vehicle_type"),
                "public_line": self._device.get("public_line"),
            }

            realtime = device_data.get("realtime", {})
            if realtime:
                if realtime.get("realtime_time"):
                    attributes["realtime_time"] = realtime["realtime_time"]
                    attributes["prediction_status"] = realtime.get("prediction_status")
                    attributes["vehicle_number"] = realtime.get("vehicle_number")
                    attributes["direction"] = realtime.get("direction")

                    delay = realtime.get("delay_minutes", 0)
                    attributes["delay_minutes"] = delay

                    if delay <= -1:
                        attributes["status"] = "early"
                        attributes["status_detail"] = f"{abs(delay)} minutes early"
                    elif delay <= 1:
                        attributes["status"] = "on_time"
                        attributes["status_detail"] = "On time"
                    elif delay <= 5:
                        attributes["status"] = "slightly_delayed"
                        attributes["status_detail"] = f"{delay} minutes delayed"
                    else:
                        attributes["status"] = "delayed"
                        attributes["status_detail"] = f"{delay} minutes delayed"

            return attributes

        except Exception as err:
            _LOGGER.error("Error getting attributes: %s", err)
            return None

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up De Lijn sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    devices = entry.data.get("devices", [])

    entities = []
    for device in devices:
        for description in SENSOR_TYPES:
            entities.append(
                DeLijnSensor(
                    coordinator=coordinator,
                    entry=entry,
                    device=device,
                    description=description,
                )
            )

    async_add_entities(entities, True)
