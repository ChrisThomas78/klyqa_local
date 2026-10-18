"""Light platform for Klyqa Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    EFFECT_OFF,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KlyqaConfigEntry, KlyqaCoordinator
from .const import CONF_PRODUCT_ID, DOMAIN
from .effects import EFFECTS
from .protocol import KlyqaError

TRANSITION_MS = 500
ROUTINE_ID = 0
EFFECT_BY_SCENE_ID = {str(scene_id): name for name, (scene_id, _) in EFFECTS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KlyqaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([KlyqaLight(entry.runtime_data, entry)])


class KlyqaLight(CoordinatorEntity[KlyqaCoordinator], LightEntity):
    """A Klyqa RGB light (bulb, strip or LED sign)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [EFFECT_OFF, *EFFECTS]

    def __init__(self, coordinator: KlyqaCoordinator, entry: KlyqaConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.unit_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.unit_id)},
            name=entry.data.get(CONF_NAME) or coordinator.unit_id,
            manufacturer="Klyqa / QConnex",
            model=entry.data.get(CONF_PRODUCT_ID),
            sw_version=(coordinator.data or {}).get("fwversion"),
        )
        self._last_static_rgb: tuple[int, int, int] | None = None
        self._remember_static_color()

    def _remember_static_color(self) -> None:
        if (self.coordinator.data or {}).get("mode") == "rgb" and self.rgb_color:
            self._last_static_rgb = self.rgb_color

    def _handle_coordinator_update(self) -> None:
        self._remember_static_color()
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        status = (self.coordinator.data or {}).get("status")
        return None if status is None else status == "on"

    @property
    def brightness(self) -> int | None:
        pct = (self.coordinator.data or {}).get("brightness", {}).get("percentage")
        return None if pct is None else round(pct * 255 / 100)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        col = (self.coordinator.data or {}).get("color")
        if not col:
            return None
        return (int(col["red"]), int(col["green"]), int(col["blue"]))

    @property
    def effect(self) -> str | None:
        data = self.coordinator.data or {}
        if data.get("mode") != "cmd":
            return EFFECT_OFF
        return EFFECT_BY_SCENE_ID.get(str(data.get("active_scene")), EFFECT_OFF)

    async def _start_effect(self, name: str) -> None:
        scene_id, commands = EFFECTS[name]
        if len(commands.split(";")) > 2:
            commands += "l 0;"  # loop multi-step scenes like the Klyqa app does
        await self._send(
            {
                "type": "routine",
                "action": "put",
                "id": ROUTINE_ID,
                "scene": str(scene_id),
                "commands": commands,
            }
        )
        await self._send({"type": "routine", "action": "start", "id": ROUTINE_ID})
        await self.coordinator.async_request_refresh()

    async def _send(self, message: dict[str, Any]) -> None:
        try:
            await self.coordinator.async_send(message)
        except KlyqaError as err:
            raise HomeAssistantError(f"Klyqa: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self._send({"type": "request", "status": "on"})
        effect = kwargs.get(ATTR_EFFECT)
        if effect in EFFECTS:
            await self._start_effect(effect)
        elif effect == EFFECT_OFF and ATTR_RGB_COLOR not in kwargs:
            # a static colour ends the running routine
            kwargs[ATTR_RGB_COLOR] = self._last_static_rgb or self.rgb_color or (255, 255, 255)
        if ATTR_RGB_COLOR in kwargs:
            red, green, blue = kwargs[ATTR_RGB_COLOR]
            await self._send(
                {
                    "type": "request",
                    "color": {"red": red, "green": green, "blue": blue},
                    "transitionTime": TRANSITION_MS,
                }
            )
        if ATTR_BRIGHTNESS in kwargs:
            pct = max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
            await self._send(
                {
                    "type": "request",
                    "brightness": {"percentage": pct},
                    "transitionTime": TRANSITION_MS,
                }
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"type": "request", "status": "off"})
