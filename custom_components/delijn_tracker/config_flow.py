# custom_components/delijn_tracker/config_flow.py
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
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_USER,
                data_schema=vol.Schema({
                    vol.Required(CONF_API_KEY): str,
                    vol.Required(CONF_HALTE_NUMBER): str,
                })
            )

        errors = {}
        self._api = DeLijnApi(
            async_get_clientsession(self.hass),
            user_input[CONF_API_KEY],
        )
        self._api_key = user_input[CONF_API_KEY]
        self._halte_number = user_input[CONF_HALTE_NUMBER]

        try:
            # Try to get halte info to validate both API key and halte number
            _LOGGER.debug("Getting available lines for halte %s", self._halte_number)
            self._available_lines = await self._api.get_available_lines(self._halte_number)
            _LOGGER.debug("Got available lines: %s", self._available_lines)

            if not self._available_lines:
                errors["base"] = "no_lines_available"
                return self.async_show_form(
                    step_id=STEP_USER,
                    data_schema=vol.Schema({
                        vol.Required(CONF_API_KEY): str,
                        vol.Required(CONF_HALTE_NUMBER): str,
                    }),
                    errors=errors,
                )

            return await self.async_step_select_line()

        except Exception as err:
            _LOGGER.error("Error validating config: %s", err)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
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
                _LOGGER.debug("Got available times: %s", self._available_times)

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
        if user_input is not None:
            scheduled_time = user_input[CONF_SCHEDULED_TIME]
            time, ritnummer = scheduled_time.split("_")

            selected_time = next(
                t for t in self._available_times
                if t["time"] == time and str(t["ritnummer"]) == ritnummer
            )

            # Create config entry
            title = f"Halte {self._halte_number} - Bus {self._line_number} - {time}"

            return self.async_create_entry(
                title=title,
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_HALTE_NUMBER: self._halte_number,
                    CONF_LINE_NUMBER: self._line_number,
                    CONF_SCHEDULED_TIME: selected_time["timestamp"],  # Use the full timestamp
                    CONF_DESTINATION: selected_time["bestemming"],
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
