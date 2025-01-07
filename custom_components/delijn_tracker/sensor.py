# custom_components/delijn_tracker/sensor.py
"""Support for De Lijn Bus Tracker sensors."""
from __future__ import annotations

from datetime import datetime
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

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="waiting_time",
        name="Waiting Time",
        icon="mdi:clock",
        native_unit_of_measurement="min",  # Keep minutes as the unit for state
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

    entities = []
    for description in SENSOR_TYPES:
        entities.append(
            DeLijnSensor(
                coordinator=coordinator,
                entry=entry,
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
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry

        self._attr_unique_id = (
            f"{entry.entry_id}_{description.key}"
        )

        # Set device info
        line_name = f"Line {entry.data.get('public_line', entry.data[CONF_LINE_NUMBER])}"
        base_name = f"{line_name} - {entry.data[CONF_DESTINATION]}"

        self._attr_name = f"{base_name} {description.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=base_name,
            manufacturer="De Lijn",
            model=entry.data.get("vehicle_type", "Bus"),
        )

    def format_waiting_time(self, minutes: float) -> str:
        """Format waiting time in d.HH:mm format."""
        total_minutes = int(round(minutes))
        days = total_minutes // (24 * 60)
        remaining_minutes = total_minutes % (24 * 60)
        hours = remaining_minutes // 60
        mins = remaining_minutes % 60
        return f"{days}.{hours:02d}:{mins:02d}"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        # Get configured time
        configured_time = self._entry.data[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM

        # Find the next occurrence of our configured time
        schedule = next(
            (time for time in self.coordinator.data.get("schedule", [])
             if time["time"] == configured_time),
            None
        )

        realtime = self.coordinator.data.get("realtime", {})

        if self.entity_description.key == "waiting_time":
            # Use real-time waiting_time if available, otherwise scheduled
            if realtime and realtime.get("realtime_time"):
                real_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                current_time = datetime.now()
                return round((real_time - current_time).total_seconds() / 60)
            elif schedule:
                return schedule["waiting_time"]

        elif self.entity_description.key == "delay":
            # Calculate delay if we have real-time data
            if realtime and realtime.get("realtime_time") and realtime.get("dienstregelingTijdstip"):
                real_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                sched_time = datetime.fromisoformat(realtime["dienstregelingTijdstip"].replace('Z', '+00:00'))
                return round((real_time - sched_time).total_seconds() / 60)

        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.data:
            return False

        # Get configured time
        configured_time = self._entry.data[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM

        # Find the next occurrence of our configured time
        schedule = next(
            (time for time in self.coordinator.data.get("schedule", [])
             if time["time"] == configured_time),
            None
        )

        return schedule is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes."""
        if not self.coordinator.data:
            return None

        # Get configured time
        configured_time = self._entry.data[CONF_SCHEDULED_TIME].split("T")[1][:5]  # Get HH:MM

        # Find the next occurrence of our configured time
        schedule = next(
            (time for time in self.coordinator.data.get("schedule", [])
             if time["time"] == configured_time),
            None
        )

        if not schedule:
            return None

        attributes = {
            "scheduled_time": schedule["time"],
            "scheduled_date": schedule["date"],
            "destination": schedule["bestemming"],
            "rit_number": schedule["ritnummer"],
            "line_description": schedule.get("line_description"),
            "vehicle_type": schedule.get("vehicle_type"),
            "public_line": schedule.get("public_line"),
        }

        # Add formatted waiting time
        waiting_time = schedule["waiting_time"]
        if self.entity_description.key == "waiting_time":
            attributes["time_formatted"] = self.format_waiting_time(waiting_time)

        realtime = self.coordinator.data.get("realtime", {})
        if realtime:
            if realtime.get("realtime_time"):
                real_time = datetime.fromisoformat(realtime["realtime_time"].replace('Z', '+00:00'))
                sched_time = datetime.fromisoformat(realtime["dienstregelingTijdstip"].replace('Z', '+00:00'))

                attributes["realtime_time"] = real_time.strftime("%H:%M")
                delay = round((real_time - sched_time).total_seconds() / 60)

                # Update waiting time format for realtime
                if self.entity_description.key == "waiting_time":
                    current_time = datetime.now()
                    realtime_waiting = round((real_time - current_time).total_seconds() / 60)
                    attributes["time_formatted"] = self.format_waiting_time(realtime_waiting)

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

                attributes["delay_minutes"] = delay

            if realtime.get("prediction_status"):
                attributes["prediction_status"] = realtime["prediction_status"]

            if realtime.get("vehicle_number"):
                attributes["vehicle_number"] = realtime["vehicle_number"]

            if realtime.get("direction"):
                attributes["direction"] = realtime["direction"]

        return attributes
