"""Config flow for Klyqa Local.

Logs in to the Klyqa cloud once to read the device list and the per-device
AES key. Only the key and device identity are stored, not the account password.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLOUD_HOST, CONF_AES_KEY, CONF_PRODUCT_ID, CONF_UNIT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "X-Request-Id": str(uuid.uuid4()),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class KlyqaLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Klyqa Local."""

    VERSION = 1

    def __init__(self) -> None:
        self._devices: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                devices = await self._async_fetch_devices(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except PermissionError:
                errors["base"] = "invalid_auth"
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
                _LOGGER.exception("Klyqa cloud request failed")
                errors["base"] = "cannot_connect"
            else:
                configured = self._async_current_ids()
                self._devices = {
                    d["localDeviceId"].upper(): d
                    for d in devices
                    if d.get("aesKey") and d.get("localDeviceId", "").upper() not in configured
                }
                if not self._devices:
                    return self.async_abort(reason="no_devices")
                return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            device = self._devices[user_input[CONF_UNIT_ID]]
            unit_id = device["localDeviceId"].upper()
            await self.async_set_unique_id(unit_id)
            self._abort_if_unique_id_configured()
            name = (device.get("name") or unit_id).strip()
            return self.async_create_entry(
                title=name,
                data={
                    CONF_UNIT_ID: unit_id,
                    CONF_AES_KEY: device["aesKey"],
                    CONF_PRODUCT_ID: device.get("productId", ""),
                    CONF_NAME: name,
                    CONF_HOST: user_input.get(CONF_HOST) or None,
                },
            )

        choices = {
            uid: f"{(d.get('name') or uid).strip()} ({d.get('productId', '?')})"
            for uid, d in self._devices.items()
        }
        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UNIT_ID, default=next(iter(choices))): vol.In(choices),
                    vol.Optional(CONF_HOST): str,
                }
            ),
        )

    async def _async_fetch_devices(self, email: str, password: str) -> list[dict[str, Any]]:
        session = async_get_clientsession(self.hass)
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(
            f"{CLOUD_HOST}/auth/login",
            json={"email": email, "password": password},
            headers=_headers(),
            timeout=timeout,
        ) as resp:
            if resp.status in (400, 401, 403):
                raise PermissionError
            resp.raise_for_status()
            token = (await resp.json())["accessToken"]
        try:
            async with session.get(
                f"{CLOUD_HOST}/settings", headers=_headers(token), timeout=timeout
            ) as resp:
                resp.raise_for_status()
                settings = await resp.json()
        finally:
            try:
                async with session.post(
                    f"{CLOUD_HOST}/auth/logout", headers=_headers(token), timeout=timeout
                ):
                    pass
            except aiohttp.ClientError:
                pass
        return settings.get("devices", [])
