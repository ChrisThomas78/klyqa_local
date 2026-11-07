"""Klyqa Local: control Klyqa/QConnex lights over the local QCX protocol."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AES_KEY,
    CONF_UNIT_ID,
    DOMAIN,
    MAX_POLL_FAILURES,
    SCAN_INTERVAL_SECONDS,
)
from .protocol import KlyqaError, KlyqaHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]

type KlyqaConfigEntry = ConfigEntry[KlyqaCoordinator]


class KlyqaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the device state and sends commands."""

    def __init__(self, hass: HomeAssistant, entry: KlyqaConfigEntry, hub: KlyqaHub) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_UNIT_ID]}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.hub = hub
        self.unit_id: str = entry.data[CONF_UNIT_ID]
        self.host: str | None = entry.data.get(CONF_HOST)
        self._key = bytes.fromhex(entry.data[CONF_AES_KEY])
        self._failures = 0

    async def async_send(self, message: dict[str, Any]) -> dict[str, Any]:
        answer = await self.hub.async_request(self.unit_id, self._key, message, self.host)
        if answer.get("type") == "status":
            self.async_set_updated_data(answer)
        return answer

    async def _async_update_data(self) -> dict[str, Any]:
        last_err: KlyqaError | None = None
        for attempt in range(2):
            try:
                data = await self.hub.async_request(
                    self.unit_id, self._key, {"type": "request"}, self.host
                )
            except KlyqaError as err:
                last_err = err
                if attempt == 0:
                    await asyncio.sleep(2)
                continue
            self._failures = 0
            return data

        # Wi-Fi devices drop single connections now and then (ESP power save);
        # keep the last known state until several polls in a row have failed.
        self._failures += 1
        if self.data is not None and self._failures < MAX_POLL_FAILURES:
            _LOGGER.debug(
                "Poll of %s failed (%s/%s), keeping last state: %s",
                self.unit_id, self._failures, MAX_POLL_FAILURES, last_err,
            )
            return self.data
        raise UpdateFailed(str(last_err)) from last_err


async def async_setup_entry(hass: HomeAssistant, entry: KlyqaConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    hub: KlyqaHub | None = domain_data.get("hub")
    if hub is None:
        hub = KlyqaHub()
        await hub.async_start()
        domain_data["hub"] = hub

    coordinator = KlyqaCoordinator(hass, entry, hub)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KlyqaConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        hub: KlyqaHub | None = hass.data.get(DOMAIN, {}).pop("hub", None)
        if hub:
            await hub.async_stop()
    return unloaded
