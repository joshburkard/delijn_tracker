"""Support for De Lijn Bus Tracker sensors."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
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
    SensorEntityDescription(
        key="latest_delay",
        name="Latest Known Delay",
        icon="mdi:clock-check",
        native_unit_of_measurement="min",
    ),
    SensorEntityDescription(
        key="expected_time",
        name="Expected Time",
        icon="mdi:clock-outline",
        native_unit_of_measurement=None,
    ),
    SensorEntityDescription(
        key="scheduled_time",
        name="Scheduled Time",
        icon="mdi:clock-time-four-outline",
        native_unit_of_measurement=None,
        #device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="delay_counter",
        name="Delay Counter",
        icon="mdi:counter",
        native_unit_of_measurement=None,
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
        public_line = device.get("public_line") or device[CONF_LINE_NUMBER]
        scheduled_time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
        vehicle_type = device.get("vehicle_type", "Bus").upper()
        halte_name = device.get("halte_name", "")

        # Create device name
        device_name = (
            f"{halte_name} ({device[CONF_HALTE_NUMBER]}) - "
            f"{vehicle_type} {public_line} - "
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
            scheduled_time = self._device[CONF_SCHEDULED_TIME].split("T")[1][:5]
            device_id = (
                f"{self._device[CONF_HALTE_NUMBER]}_"
                f"{self._device[CONF_LINE_NUMBER]}_"
                f"{scheduled_time}"
            )

            device_data = self.coordinator.data.get(device_id, {})
            if not device_data:
                return None

            schedule = next(
                (time for time in device_data.get("schedule", [])
                 if time["time"] == scheduled_time),
                None
            )

            if not schedule:
                return None

            if self.entity_description.key == "scheduled_time":
                time = datetime.fromisoformat(schedule["timestamp"].replace('Z', '+00:00'))
                return time.strftime("%H:%M")

                #if schedule and schedule.get("timestamp"):
                #    # Return the scheduled time as a timestamp
                #    return datetime.fromisoformat(
                #        schedule["timestamp"].replace('Z', '+00:00')
                #    ).isoformat()

                return None

            elif self.entity_description.key == "delay_counter":
                delay_stats = device_data.get("delay_stats", {})
                return delay_stats.get("delay_counter", 0)

            elif self.entity_description.key == "expected_time":
                realtime = device_data.get("realtime", {})

                if realtime and realtime.get("realtime_time"):
                    # Use realtime prediction if available
                    time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                    return time.strftime("%H:%M")
                elif schedule and schedule.get("timestamp"):
                    # Fall back to scheduled time
                    time = datetime.fromisoformat(schedule["timestamp"].replace('Z', '+00:00'))
                    return time.strftime("%H:%M")

                return None

            elif self.entity_description.key == "waiting_time":
                now = datetime.now()
                realtime = device_data.get("realtime", {})

                if realtime and realtime.get("realtime_time"):
                    target_time = datetime.fromisoformat(
                        realtime["realtime_time"].replace('Z', '+00:00')
                    )
                    if target_time < now:
                        return "00:00"
                else:
                    target_time = datetime.fromisoformat(
                        schedule["timestamp"].replace('Z', '+00:00')
                    )
                    while target_time < now:
                        target_time = target_time + timedelta(days=1)

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
                if realtime and realtime.get("realtime_time") and realtime.get("dienstregelingTijdstip"):
                    real_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                    sched_time = datetime.fromisoformat(realtime["dienstregelingTijdstip"].replace('Z', '+00:00'))
                    delay = round((real_time - sched_time).total_seconds() / 60)
                    if delay != 0:
                        _LOGGER.info(
                            "Found delay of %d minutes for line %s",
                            delay,
                            self._device[CONF_LINE_NUMBER]
                        )
                    return delay
                return None

            elif self.entity_description.key == "latest_delay":
                # First check for current realtime data
                realtime = device_data.get("realtime", {})
                latest_delay = device_data.get("latest_delay")

                if realtime and realtime.get("realtime_time") and latest_delay is not None:
                    return latest_delay

                # If no current realtime data, check stored delay
                last_known_delay = device_data.get("last_known_delay")
                last_delay_date = device_data.get("last_delay_date")

                if last_known_delay is not None and last_delay_date:
                    # Only use last known delay if it's from today
                    today = datetime.now().date().isoformat()
                    if last_delay_date == today:
                        return last_known_delay

                return None


        except Exception as err:
            _LOGGER.error("Error getting native value: %s", err)
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes."""
        from .const import (
            DELAY_HIGH_LABEL, DELAY_MEDIUM_LABEL, DELAY_LOW_LABEL,
            EARLY_HIGH_LABEL, EARLY_MEDIUM_LABEL, EARLY_LOW_LABEL
        )

        if not self.coordinator.data:
            return None

        try:
            scheduled_time = self._device[CONF_SCHEDULED_TIME].split("T")[1][:5]
            device_id = (
                f"{self._device[CONF_HALTE_NUMBER]}_"
                f"{self._device[CONF_LINE_NUMBER]}_"
                f"{scheduled_time}"
            )
            device_data = self.coordinator.data.get(device_id, {})

            attributes = {
                "scheduled_time": scheduled_time,
                "destination": self._device[CONF_DESTINATION],
                "line_description": self._device.get("line_description"),
                "vehicle_type": self._device.get("vehicle_type"),
                "public_line": self._device.get("public_line"),
            }

            if self.entity_description.key == "delay_counter":
                delay_stats = device_data.get("delay_stats", {})
                attributes.update({
                    DELAY_HIGH_LABEL: delay_stats.get("high_delay", 0),
                    DELAY_MEDIUM_LABEL: delay_stats.get("medium_delay", 0),
                    DELAY_LOW_LABEL: delay_stats.get("low_delay", 0),
                    EARLY_HIGH_LABEL: delay_stats.get("high_early", 0),
                    EARLY_MEDIUM_LABEL: delay_stats.get("medium_early", 0),
                    EARLY_LOW_LABEL: delay_stats.get("low_early", 0),
                })

                # Add last delay date if available
                if device_data.get("last_delay_date"):
                    attributes["Last Delay Date"] = device_data["last_delay_date"]

            if self.entity_description.key == "latest_delay":
                last_update = device_data.get("last_delay_update")
                if last_update:
                    attributes["last_delay_update"] = last_update.isoformat()

                # Add last known delay information
                last_known_delay = device_data.get("last_known_delay")
                last_delay_date = device_data.get("last_delay_date")
                if last_known_delay is not None:
                    attributes["last_known_delay"] = last_known_delay
                if last_delay_date:
                    attributes["last_delay_date"] = last_delay_date

            realtime = device_data.get("realtime", {})
            if realtime:
                if realtime.get("realtime_time"):
                    attributes["realtime_time"] = realtime["realtime_time"]
                    attributes["prediction_status"] = realtime.get("prediction_status")
                    attributes["vehicle_number"] = realtime.get("vehicle_number")
                    attributes["direction"] = realtime.get("direction")

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
