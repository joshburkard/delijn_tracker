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
            # Get entities first
            entities = await self._make_request("entiteiten")

            # Find the halte in any entity
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
                _LOGGER.error("Halte %s not found", halte_number)
                return []

            # Get lijnrichtingen
            lijnrichtingen_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "lijnrichtingen"),
                None
            )

            if not lijnrichtingen_link:
                return []

            lijnrichtingen_data = await self._make_request_with_url(lijnrichtingen_link)
            _LOGGER.debug("Got lijnrichtingen data: %s", lijnrichtingen_data)

            # Process each line
            lines = []
            for lr in lijnrichtingen_data.get("lijnrichtingen", []):
                try:
                    # Get line details
                    line_data = await self._make_request(
                        f"lijnen/1/{lr['lijnnummer']}/lijnrichtingen/HEEN"
                    )
                    lines.append({
                        "lijnnummer": lr["lijnnummer"],
                        "omschrijving": line_data.get("omschrijving", ""),
                        "bestemming": line_data.get("bestemming", "Unknown"),
                    })
                except Exception as e:
                    _LOGGER.warning("Error getting line details for %s: %s", lr.get("lijnnummer"), e)

            return lines

        except Exception as err:
            _LOGGER.error("Error getting available lines: %s", err)
            raise

    async def get_schedule_times(
        self,
        halte_number: str,
        line_number: str,
        target_time: str = None
    ) -> list[dict[str, Any]]:
        """Get scheduled times for a specific line at a halte."""
        try:
            _LOGGER.debug("Getting schedule times for halte %s, line %s, target %s",
                         halte_number, line_number, target_time)

            # Find halte in entities
            entities = await self._make_request("entiteiten")
            halte = None
            entity_number = None

            for entity in entities["entiteiten"]:
                try:
                    halte_response = await self._make_request(f"haltes/{entity['entiteitnummer']}/{halte_number}")
                    if halte_response:
                        halte = halte_response
                        entity_number = entity['entiteitnummer']
                        break
                except Exception:
                    continue

            if not halte:
                _LOGGER.error("Halte %s not found", halte_number)
                return []

            # Get dienstregelingen directly from halte
            dienstregelingen_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "dienstregelingen"),
                None
            )
            if not dienstregelingen_link:
                return []

            # Get line details
            line_detail = await self._get_line_details(entity_number, line_number)

            # Function to get doorkomsten for a specific date
            async def get_doorkomsten_for_date(date_str=None):
                url = dienstregelingen_link
                if date_str:
                    url = f"{dienstregelingen_link}?datum={date_str}"

                data = await self._make_request_with_url(url)
                doorkomsten = []

                if isinstance(data.get("halteDoorkomsten"), list):
                    for doorkomst in data["halteDoorkomsten"][0].get("doorkomsten", []):
                        if str(doorkomst.get("lijnnummer")) == line_number:
                            doorkomsten.append(doorkomst)

                return doorkomsten

            # Start with today's doorkomsten
            all_doorkomsten = []
            current_date = datetime.now()
            current_doorkomsten = await get_doorkomsten_for_date()

            # If we have a target time
            if target_time:
                # Check if target time is in the past for today
                target_parts = target_time.split(":")
                target_hour = int(target_parts[0])
                target_minute = int(target_parts[1])
                current_time = current_date.replace(microsecond=0)
                target_today = current_time.replace(
                    hour=target_hour,
                    minute=target_minute,
                    second=0
                )

                if target_today < current_time:
                    # Target time has passed today, get next days until we find it
                    for _ in range(7):  # Try next 7 days
                        current_date = current_date + timedelta(days=1)
                        date_str = current_date.strftime("%Y-%m-%d")
                        future_doorkomsten = await get_doorkomsten_for_date(date_str)

                        # Check if any doorkomst matches our target time
                        for doorkomst in future_doorkomsten:
                            dtime = datetime.fromisoformat(
                                doorkomst["dienstregelingTijdstip"].replace('Z', '+00:00')
                            )
                            if dtime.hour == target_hour and dtime.minute == target_minute:
                                all_doorkomsten.append(doorkomst)
                                break

                        if all_doorkomsten:  # Found our time
                            break
                else:
                    # Target time is still to come today
                    all_doorkomsten = current_doorkomsten
            else:
                all_doorkomsten = current_doorkomsten

            # Process doorkomsten
            processed_times = []
            current_time = datetime.now()

            for doorkomst in all_doorkomsten:
                scheduled_time_str = doorkomst.get("dienstregelingTijdstip")
                if not scheduled_time_str:
                    continue

                try:
                    scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                    waiting_time = (scheduled_time - current_time).total_seconds() / 60

                    time_entry = {
                        "time": scheduled_time.strftime("%H:%M"),
                        "timestamp": scheduled_time_str,
                        "waiting_time": round(waiting_time),
                        "bestemming": doorkomst.get("bestemming", "Unknown"),
                        "ritnummer": doorkomst.get("ritnummer"),
                        "vehicle_type": line_detail.get("vervoertype"),
                        "public_line": line_detail.get("lijnnummerPubliek", line_number),
                        "line_description": line_detail.get("omschrijving"),
                        "date": scheduled_time.strftime("%Y-%m-%d"),
                    }
                    processed_times.append(time_entry)

                except Exception as e:
                    _LOGGER.warning("Error processing time %s: %s", scheduled_time_str, e)

            return sorted(processed_times, key=lambda x: x["waiting_time"])

            # Process each doorkomst
            processed_times = []
            current_time = datetime.now()

            for doorkomst in doorkomsten:
                scheduled_time_str = doorkomst.get("dienstregelingTijdstip")
                if not scheduled_time_str:
                    continue

                try:
                    scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                    waiting_time = (scheduled_time - current_time).total_seconds() / 60

                    time_entry = {
                        "time": scheduled_time.strftime("%H:%M"),
                        "timestamp": scheduled_time_str,
                        "waiting_time": round(waiting_time),
                        "bestemming": doorkomst.get("bestemming", "Unknown"),
                        "ritnummer": doorkomst.get("ritnummer"),
                        "vehicle_type": line_detail.get("vervoertype"),
                        "public_line": line_detail.get("lijnnummerPubliek", line_number),
                        "line_description": line_detail.get("omschrijving"),
                    }
                    processed_times.append(time_entry)

                except Exception as e:
                    _LOGGER.warning("Error processing time %s: %s", scheduled_time_str, e)

            return sorted(processed_times, key=lambda x: x["waiting_time"])

        except Exception as err:
            _LOGGER.error("Error fetching schedule data: %s", err)
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

            # Filter for future times
            current_time = datetime.now()
            times = []

            for doorkomst in doorkomsten:
                scheduled_time_str = doorkomst.get("dienstregelingTijdstip")
                if not scheduled_time_str:
                    continue

                try:
                    scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                    if scheduled_time > current_time:
                        time_entry = {
                            "time": scheduled_time.strftime("%H:%M"),
                            "bestemming": doorkomst["bestemming"],
                            "timestamp": scheduled_time_str,
                            "ritnummer": doorkomst["ritnummer"]
                        }
                        _LOGGER.debug("Adding time entry: %s", time_entry)
                        times.append(time_entry)

                except Exception as e:
                    _LOGGER.warning("Error processing time %s: %s", scheduled_time_str, e)

            _LOGGER.debug("Returning %d schedule times", len(times))
            return sorted(times, key=lambda x: x["time"])

        except Exception as err:
            _LOGGER.error("Error fetching schedule data: %s", err)
            raise

    async def get_realtime_data(
        self,
        halte_number: str,
        line_number: str,
        scheduled_time: str,
    ) -> dict[str, Any]:
        """Get real-time data for a specific scheduled time."""
        try:
            # Find halte in entities
            entities = await self._make_request("entiteiten")
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
                return {}

            # Get real-time data directly from halte
            realtime_link = next(
                (link["url"] for link in halte["links"] if link["rel"] == "real-time"),
                None
            )

            if not realtime_link:
                return {}

            realtime_data = await self._make_request_with_url(realtime_link)
            _LOGGER.debug("Got realtime data: %s", realtime_data)

            # Process doorkomsten
            if isinstance(realtime_data.get("halteDoorkomsten"), list):
                doorkomsten = realtime_data["halteDoorkomsten"][0].get("doorkomsten", [])
                for doorkomst in doorkomsten:
                    if (str(doorkomst.get("lijnnummer")) == line_number and
                        doorkomst.get("dienstregelingTijdstip") == scheduled_time):
                        _LOGGER.debug("Found matching realtime doorkomst: %s", doorkomst)
                        return {
                            "dienstregelingTijdstip": doorkomst.get("dienstregelingTijdstip"),
                            "realtime_time": doorkomst.get("real-timeTijdstip"),
                            "prediction_status": doorkomst.get("predictionStatussen", [])[0] if doorkomst.get("predictionStatussen") else None,
                            "vehicle_number": doorkomst.get("vrtnum"),
                            "direction": doorkomst.get("richting"),
                        }

        except Exception as err:
            _LOGGER.error("Error getting real-time data: %s", err)

        return {}
