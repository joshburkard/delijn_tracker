"""Config flow for De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DeLijnApi
from .const import (
    DOMAIN,
    CONF_HALTE_NUMBER,
    CONF_LINE_NUMBER,
    CONF_SCHEDULED_TIME,
    CONF_DESTINATION,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_KEY): str,
})

class DeLijnTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for De Lijn Tracker integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api: DeLijnApi | None = None
        self._api_key: str | None = None
        self._halte_number: str | None = None
        self._available_lines: list[dict[str, Any]] | None = None
        self._line_number: str | None = None
        self._available_times: list[dict[str, Any]] | None = None
        self._entity_number: str | None = None
        self._existing_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        errors = {}

        if existing_entries := self._async_current_entries():
            self._existing_entry = existing_entries[0]
            self._api_key = self._existing_entry.data[CONF_API_KEY]
            self._api = DeLijnApi(
                async_get_clientsession(self.hass),
                self._api_key,
            )
            return await self.async_step_halte()

        if user_input is not None:
            try:
                api = DeLijnApi(
                    async_get_clientsession(self.hass),
                    user_input[CONF_API_KEY],
                )
                await api.validate_config("100", "1")
                self._api = api
                self._api_key = user_input[CONF_API_KEY]
                return await self.async_step_halte()
            except Exception:
                _LOGGER.exception("Failed to connect to De Lijn API")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_halte(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle halte number input."""
        errors = {}

        if user_input is not None:
            try:
                self._halte_number = user_input[CONF_HALTE_NUMBER]
                self._available_lines = await self._api.get_available_lines(self._halte_number)
                if self._available_lines:
                    return await self.async_step_select_line()
                errors["base"] = "no_lines_available"
            except Exception:
                _LOGGER.exception("Failed to get available lines")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="halte",
            data_schema=vol.Schema({
                vol.Required(CONF_HALTE_NUMBER): str,
            }),
            errors=errors,
        )

    async def async_step_select_line(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle line selection."""
        errors = {}

        if user_input is not None:
            try:
                selected_line = next(
                    line for line in self._available_lines
                    if str(line["lijnnummer"]) == user_input[CONF_LINE_NUMBER]
                )

                self._line_number = str(selected_line["lijnnummer"])
                self._entity_number = selected_line.get("entity_number")

                _LOGGER.debug(
                    "Getting schedule times for halte %s, line %s",
                    self._halte_number,
                    self._line_number
                )

                self._available_times = await self._api.get_schedule_times(
                    self._halte_number,
                    self._line_number,
                    entity_number=self._entity_number
                )

                if self._available_times:
                    return await self.async_step_select_time()

                errors["base"] = "no_times_available"
            except Exception as err:
                _LOGGER.exception("Failed to get schedule times: %s", err)
                errors["base"] = "cannot_connect"

        if not self._available_lines:
            return await self.async_step_halte()

        line_options = {
            str(line["lijnnummer"]): f"Line {line['lijnnummer']} - {line.get('omschrijving', '')}"
            for line in self._available_lines
        }

        return self.async_show_form(
            step_id="select_line",
            data_schema=vol.Schema({
                vol.Required(CONF_LINE_NUMBER): vol.In(line_options)
            }),
            errors=errors,
        )

    async def async_step_select_time(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle time selection."""
        if user_input is not None:
            try:
                scheduled_time = user_input[CONF_SCHEDULED_TIME]
                time, ritnummer = scheduled_time.split("_")

                selected_time = next(
                    t for t in self._available_times
                    if t["time"] == time and str(t["ritnummer"]) == ritnummer
                )

                selected_line = next(
                    line for line in self._available_lines
                    if str(line["lijnnummer"]) == self._line_number
                )

                device_unique_id = f"{self._halte_number}_{self._line_number}_{time}"
                device_data = {
                    CONF_HALTE_NUMBER: self._halte_number,
                    CONF_LINE_NUMBER: self._line_number,
                    CONF_SCHEDULED_TIME: selected_time["timestamp"],
                    CONF_DESTINATION: selected_time["bestemming"],
                    "public_line": selected_line.get("lijnnummerPubliek", self._line_number),
                    "vehicle_type": "Bus",
                    "line_description": selected_line.get("omschrijving", f"Line {self._line_number}"),
                    "entity_number": selected_line.get("entity_number"),
                    "halte_name": selected_line.get("halte_name", ""),
                    "unique_id": device_unique_id
                }

                if self._existing_entry:
                    new_data = dict(self._existing_entry.data)
                    devices = list(new_data.get("devices", []))
                    devices.append(device_data)
                    new_data["devices"] = devices

                    self.hass.config_entries.async_update_entry(
                        self._existing_entry,
                        data=new_data
                    )
                    return self.async_abort(reason="device_added")

                return self.async_create_entry(
                    title=f"{selected_line.get('halte_name', '')} - Line {selected_line.get('lijnnummerPubliek', self._line_number)}",
                    data={
                        CONF_API_KEY: self._api_key,
                        "devices": [device_data]
                    }
                )

            except Exception as err:
                _LOGGER.info("Error in time selection: %s", err)
                return self.async_abort(reason="time_error")

        time_options = {
            f"{time['time']}_{time['ritnummer']}": (
                f"{time['time']} - {time['bestemming']}"
            )
            for time in self._available_times or []
        }

        return self.async_show_form(
            step_id="select_time",
            data_schema=vol.Schema({
                vol.Required(CONF_SCHEDULED_TIME): vol.In(time_options)
            })
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle De Lijn Tracker options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        errors = {}

        if user_input is not None:
            try:
                if user_input["remove_device"] != "none":
                    data = dict(self.config_entry.data)
                    devices = list(data.get("devices", []))

                    # Find device to remove
                    device_to_remove = next(
                        (dev for dev in devices
                        if dev.get("unique_id") == user_input["remove_device"]),
                        None
                    )

                    if device_to_remove:
                        _LOGGER.info(
                            "Removing device: Halte %s Line %s Time %s",
                            device_to_remove[CONF_HALTE_NUMBER],
                            device_to_remove[CONF_LINE_NUMBER],
                            device_to_remove[CONF_SCHEDULED_TIME].split("T")[1][:5]
                        )

                        # Remove from device registry
                        device_registry = dr.async_get(self.hass)
                        unique_id = f"{self.config_entry.entry_id}_{device_to_remove['unique_id']}"
                        device = device_registry.async_get_device({(DOMAIN, unique_id)})

                        if device:
                            device_registry.async_remove_device(device.id)
                            _LOGGER.info("Device removed from registry")

                        # Update configuration
                        devices = [dev for dev in devices if dev.get("unique_id") != user_input["remove_device"]]
                        data["devices"] = devices

                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data=data
                        )

                        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                        return self.async_create_entry(title="", data={})

                    errors["base"] = "device_not_found"
                    _LOGGER.info("Selected device not found in configuration")

            except Exception as err:
                _LOGGER.exception("Error removing device: %s", err)
                errors["base"] = "unknown"

        # Create list of devices
        devices = self.config_entry.data.get("devices", [])
        device_options = {
            "none": "Don't remove any device"
        }

        for device in devices:
            halte = device[CONF_HALTE_NUMBER]
            line = device[CONF_LINE_NUMBER]
            time = device[CONF_SCHEDULED_TIME].split("T")[1][:5]
            destination = device[CONF_DESTINATION]
            unique_id = device.get("unique_id", f"{halte}_{line}_{time}")

            device_options[unique_id] = (
                f"Halte {halte} - Line {line} - {destination} - {time}"
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    "remove_device",
                    default="none"
                ): vol.In(device_options)
            }),
            errors=errors
        )
