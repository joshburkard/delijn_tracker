"""Config flow for De Lijn Bus Tracker integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_HALTE_NUMBER,
    CONF_LINE_NUMBER,
    CONF_SCHEDULED_TIME,
    CONF_DESTINATION,
    STEP_USER,
    STEP_SELECT_LINE,
    STEP_SELECT_TIME,
)
from .api import DeLijnApi

_LOGGER = logging.getLogger(__name__)

class DeLijnConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for De Lijn Bus Tracker."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._api: DeLijnApi | None = None
        self._api_key: str | None = None
        self._halte_number: str | None = None
        self._available_lines: list[dict[str, Any]] | None = None
        self._line_number: str | None = None
        self._available_times: list[dict[str, Any]] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Check if we already have an entry
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if entries:
            # Get API key from existing entry
            entry = entries[0]
            self._api_key = entry.data[CONF_API_KEY]
            self._api = DeLijnApi(
                async_get_clientsession(self.hass),
                self._api_key,
            )
            return await self.async_step_halte()

        # First time setup - ask for API key
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_USER,
                data_schema=vol.Schema({
                    vol.Required(CONF_API_KEY): str,
                })
            )

        # Validate API key
        try:
            self._api = DeLijnApi(
                async_get_clientsession(self.hass),
                user_input[CONF_API_KEY],
            )
            self._api_key = user_input[CONF_API_KEY]

            # Store API key and continue to halte selection
            _LOGGER.debug("API key validated, continuing to halte selection")
            return await self.async_step_halte()
        except Exception as err:
            _LOGGER.error("Error validating API key: %s", err)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    async def async_step_halte(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle halte number input."""
        errors = {}

        if user_input is not None:
            self._halte_number = user_input[CONF_HALTE_NUMBER]
            try:
                _LOGGER.debug("Getting available lines for halte %s", self._halte_number)
                self._available_lines = await self._api.get_available_lines(self._halte_number)
                if not self._available_lines:
                    errors["base"] = "no_lines_available"
                else:
                    return await self.async_step_select_line()
            except Exception as err:
                _LOGGER.error("Error getting lines: %s", err)
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
        if user_input is not None:
            self._line_number = user_input[CONF_LINE_NUMBER]
            try:
                _LOGGER.debug("Getting schedule times for halte %s, line %s",
                            self._halte_number, self._line_number)
                self._available_times = await self._api.get_schedule_times(
                    self._halte_number,
                    self._line_number,
                )
                if self._available_times:
                    return await self.async_step_select_time()
                else:
                    return self.async_abort(reason="no_times_available")
            except Exception as err:
                _LOGGER.error("Error getting schedule times: %s", err)
                return self.async_abort(reason="cannot_connect")

        line_options = {
            str(line["lijnnummer"]): f"Line {line['lijnnummer']} - {line['omschrijving']}"
            for line in self._available_lines
        }

        return self.async_show_form(
            step_id=STEP_SELECT_LINE,
            data_schema=vol.Schema({
                vol.Required(CONF_LINE_NUMBER): vol.In(line_options)
            })
        )

    async def async_step_select_time(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle time selection."""
        _LOGGER.debug("Starting async_step_select_time with user_input: %s", user_input)

        if user_input is not None:
            scheduled_time = user_input[CONF_SCHEDULED_TIME]
            time, ritnummer = scheduled_time.split("_")
            _LOGGER.debug("Processing selected time: %s with ritnummer: %s", time, ritnummer)

            selected_time = next(
                t for t in self._available_times
                if t["time"] == time and str(t["ritnummer"]) == ritnummer
            )
            _LOGGER.debug("Found selected time details: %s", selected_time)

            # Prepare device data
            device_data = {
                CONF_HALTE_NUMBER: self._halte_number,
                CONF_LINE_NUMBER: self._line_number,
                CONF_SCHEDULED_TIME: selected_time["timestamp"],
                CONF_DESTINATION: selected_time["bestemming"],
                "public_line": selected_time.get("public_line"),
                "vehicle_type": selected_time.get("vehicle_type"),
                "line_description": selected_time.get("line_description"),
            }
            _LOGGER.debug("Prepared device data: %s", device_data)

            # Get entries
            entries = self.hass.config_entries.async_entries(DOMAIN)
            _LOGGER.debug("Found %d existing entries", len(entries))

            if entries:
                # Adding device to existing entry
                entry = entries[0]
                _LOGGER.debug("Working with existing entry: %s", entry.entry_id)
                _LOGGER.debug("Current entry data: %s", entry.data)

                existing_data = dict(entry.data)
                devices = list(existing_data.get("devices", []))
                _LOGGER.debug("Current devices: %s", devices)

                devices.append(device_data)
                existing_data["devices"] = devices

                _LOGGER.debug("Updating entry with new data: %s", existing_data)

                try:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data=existing_data
                    )
                    _LOGGER.debug("Successfully updated entry")
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="device_added")
                except Exception as err:
                    _LOGGER.error("Error updating entry: %s", err, exc_info=True)
                    raise
            else:
                # Creating new entry with first device
                _LOGGER.debug("Creating new entry with first device")
                title = "De Lijn Tracker"
                _LOGGER.debug("Creating entry with title: %s", title)
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_API_KEY: self._api_key,
                        "devices": [device_data]
                    }
                )

        time_options = {
            f"{time['time']}_{time['ritnummer']}": f"{time['time']} - {time['bestemming']}"
            for time in self._available_times
        }

        return self.async_show_form(
            step_id=STEP_SELECT_TIME,
            data_schema=vol.Schema({
                vol.Required(CONF_SCHEDULED_TIME): vol.In(time_options)
            })
        )
