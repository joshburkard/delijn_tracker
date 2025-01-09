# custom_components/delijn_tracker/api.py
"""API client for De Lijn."""
from __future__ import annotations

import logging
from typing import Any
from datetime import datetime, timedelta

from aiohttp import ClientSession

_LOGGER = logging.getLogger(__name__)

class DeLijnApi:
    """De Lijn API client."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        """Initialize the API client."""
        self._session = session
        self._api_key = api_key
        self._base_url = "https://api.delijn.be/DLKernOpenData/api/v1"
        self._halte_entities = {}  # Store halte to entity mapping

    async def _make_request(self, endpoint: str) -> Any:
        """Make a request to the De Lijn API."""
        headers = {'Ocp-Apim-Subscription-Key': self._api_key}
        url = f"{self._base_url}/{endpoint}"
        _LOGGER.debug("Making request to: %s", url)
        async with self._session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    async def _make_request_with_url(self, url: str) -> Any:
        """Make a request to a specific URL."""
        headers = {'Ocp-Apim-Subscription-Key': self._api_key}
        _LOGGER.debug("Making request to: %s", url)
        async with self._session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    async def _get_entity_for_halte(self, halte_number: str) -> str | None:
        """Get the correct entity number for a halte."""
        # Check if we already know the entity for this halte
        if halte_number in self._halte_entities:
            return self._halte_entities[halte_number]

        # If not, find it
        entities = await self._make_request("entiteiten")
        for entity in entities["entiteiten"]:
            try:
                halte_response = await self._make_request(
                    f"haltes/{entity['entiteitnummer']}/{halte_number}"
                )
                if halte_response:
                    self._halte_entities[halte_number] = entity['entiteitnummer']
                    return entity['entiteitnummer']
            except Exception:
                continue
        return None

    async def get_schedule_times(
        self,
        halte_number: str,
        line_number: str,
        target_time: str = None,
        entity_number: str = None
    ) -> list[dict[str, Any]]:
        """Get scheduled times for a specific line at a halte."""
        try:
            _LOGGER.debug(
                "Getting schedule times for halte %s, line %s, target %s",
                halte_number, line_number, target_time
            )

            # Get entity if not provided
            if not entity_number:
                entity_number = await self._get_entity_for_halte(halte_number)

            if not entity_number:
                _LOGGER.error("Could not find entity for halte %s", halte_number)
                return []

            # Get halte details
            halte = await self._make_request(f"haltes/{entity_number}/{halte_number}")
            if not halte:
                _LOGGER.error("Could not get halte details for %s", halte_number)
                return []

            # Get dienstregelingen
            dienstregelingen_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "dienstregelingen"),
                None
            )
            if not dienstregelingen_link:
                _LOGGER.error("No dienstregelingen link found for halte %s", halte_number)
                return []

            data = await self._make_request_with_url(dienstregelingen_link)
            schedule_times = []

            if isinstance(data.get("halteDoorkomsten"), list):
                for doorkomst in data["halteDoorkomsten"][0].get("doorkomsten", []):
                    if str(doorkomst.get("lijnnummer")) == line_number:
                        departure_time = datetime.fromisoformat(
                            doorkomst["dienstregelingTijdstip"].replace('Z', '+00:00')
                        )
                        time_str = departure_time.strftime("%H:%M")

                        if target_time and time_str != target_time:
                            continue

                        schedule_times.append({
                            "time": time_str,
                            "timestamp": doorkomst["dienstregelingTijdstip"],
                            "bestemming": doorkomst.get("bestemming", "Unknown"),
                            "ritnummer": doorkomst["ritnummer"],
                            "date": departure_time.strftime("%Y-%m-%d"),
                            "entity_number": entity_number
                        })

            _LOGGER.debug(
                "Found %d schedule times for halte %s, line %s",
                len(schedule_times), halte_number, line_number
            )
            return sorted(schedule_times, key=lambda x: x["time"])

        except Exception as err:
            _LOGGER.error("Error fetching schedule data: %s", err)
            return []

    async def get_realtime_data(
        self,
        halte_number: str,
        line_number: str,
        scheduled_time: str,
    ) -> dict[str, Any]:
        """Get real-time data for a specific scheduled time."""
        try:
            # Get entities first
            entities = await self._make_request("entiteiten")

            # Find halte in entities
            halte = None
            for entity in entities["entiteiten"]:
                try:
                    halte_response = await self._make_request(
                        f"haltes/{entity['entiteitnummer']}/{halte_number}"
                    )
                    if halte_response:
                        halte = halte_response
                        _LOGGER.debug("Found halte in entity %s", entity['entiteitnummer'])
                        break
                except Exception:
                    continue

            if not halte:
                _LOGGER.debug("No halte found for %s", halte_number)
                return {}

            # Get real-time data directly from halte
            realtime_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "real-time"),
                None
            )

            if not realtime_link:
                _LOGGER.debug("No real-time link found for halte %s", halte_number)
                return {}

            realtime_data = await self._make_request_with_url(realtime_link)
            _LOGGER.debug("Got realtime data: %s", realtime_data)

            # Process doorkomsten with safer list access
            halte_doorkomsten = realtime_data.get("halteDoorkomsten", [])
            if not halte_doorkomsten:
                _LOGGER.debug("No halte doorkomsten found")
                return {}

            first_doorkomsten = halte_doorkomsten[0] if halte_doorkomsten else {}
            doorkomsten = first_doorkomsten.get("doorkomsten", [])

            for doorkomst in doorkomsten:
                if (str(doorkomst.get("lijnnummer")) == line_number and
                    doorkomst.get("dienstregelingTijdstip") == scheduled_time):
                    _LOGGER.debug("Found matching realtime doorkomst: %s", doorkomst)
                    return {
                        "dienstregelingTijdstip": doorkomst.get("dienstregelingTijdstip"),
                        "realtime_time": doorkomst.get("real-timeTijdstip"),
                        "prediction_status": (doorkomst.get("predictionStatussen") or [None])[0],
                        "vehicle_number": doorkomst.get("vrtnum"),
                        "direction": doorkomst.get("richting"),
                    }

            _LOGGER.debug(
                "No matching realtime data found for line %s at time %s",
                line_number, scheduled_time
            )
            return {}

        except Exception as err:
            _LOGGER.error("Error getting real-time data: %s", err)
            return {}

    async def validate_config(
        self,
        halte_number: str,
        line_number: str,
    ) -> bool:
        """Validate the configuration parameters."""
        try:
            # Get entities first
            entities = await self._make_request("entiteiten")

            # Try to get halte info for each entity
            halte = None
            for entity in entities["entiteiten"]:
                try:
                    halte_response = await self._make_request(f"haltes/{entity['entiteitnummer']}/{halte_number}")
                    if halte_response:
                        halte = halte_response
                        break
                except Exception:
                    continue

            if not halte:
                return False

            # Get lines for this halte
            lijnrichtingen_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "lijnrichtingen"),
                None
            )

            if not lijnrichtingen_link:
                return False

            lijnrichtingen_data = await self._make_request_with_url(lijnrichtingen_link)
            return any(
                str(lr.get("lijnnummer")) == line_number
                for lr in lijnrichtingen_data.get("lijnrichtingen", [])
            )

        except Exception as err:
            _LOGGER.error("Error validating config: %s", err)
            raise

    async def get_available_lines(self, halte_number: str) -> list[dict[str, Any]]:
        """Get available lines for a halte."""
        try:
            entities = await self._make_request("entiteiten")
            lines = []
            halte = None
            entity_number = None
            halte_name = None

            for entity in entities["entiteiten"]:
                try:
                    halte_response = await self._make_request(
                        f"haltes/{entity['entiteitnummer']}/{halte_number}"
                    )
                    if halte_response:
                        halte = halte_response
                        entity_number = entity['entiteitnummer']
                        halte_name = halte_response.get("omschrijvingLang", "")
                        _LOGGER.debug("Found halte in entity %s", entity_number)
                        break
                except Exception:
                    continue

            if not halte:
                _LOGGER.error("Halte %s not found", halte_number)
                return []

            lijnrichtingen_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "lijnrichtingen"),
                None
            )

            if not lijnrichtingen_link:
                return []

            lijnrichtingen_data = await self._make_request_with_url(lijnrichtingen_link)

            for lr in lijnrichtingen_data.get("lijnrichtingen", []):
                try:
                    line_data = None
                    for entity in entities["entiteiten"]:
                        try:
                            entity_line_data = await self._make_request(
                                f"lijnen/{entity['entiteitnummer']}/{lr['lijnnummer']}"
                            )
                            if entity_line_data:
                                if isinstance(entity_line_data, list):
                                    line_data = next((line for line in entity_line_data if line.get("publiek")), None)
                                else:
                                    line_data = entity_line_data
                                break
                        except Exception:
                            continue

                    if line_data:
                        lines.append({
                            "lijnnummer": lr["lijnnummer"],
                            "lijnnummerPubliek": line_data.get("lijnnummerPubliek", lr["lijnnummer"]),
                            "omschrijving": line_data.get("omschrijving", ""),
                            "bestemming": line_data.get("bestemming", "Unknown"),
                            "entity_number": entity_number,
                            "halte_name": halte_name
                        })

                except Exception as e:
                    _LOGGER.info(
                        "Error getting line details for %s: %s",
                        lr.get("lijnnummer"),
                        str(e)
                    )

            return sorted(lines, key=lambda x: int(x["lijnnummer"]))
        except Exception as err:
            _LOGGER.error("Error getting available lines: %s", err)
            raise

    async def _get_line_details(
        self,
        entity_number: str,
        line_number: str,
    ) -> dict:
        """Get detailed line information."""
        try:
            response = await self._make_request(f"lijnen/{entity_number}/{line_number}")
            if isinstance(response, list):
                for line in response:
                    if line.get("publiek"):
                        return line
            return response if isinstance(response, dict) else {}
        except Exception as err:
            _LOGGER.error("Error getting line details: %s", err)
            return {}
