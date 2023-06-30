"""Support for BoschTT ac."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import pyboschtt
import voluptuous as vol

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    SWING_BOTH,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    SWING_VERTICAL,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_NAME,
    ATTR_TEMPERATURE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)


HA_STATE_TO_BOSCH = {
    HVACMode.FAN_ONLY: "fanOnly",
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "heat",
    HVACMode.HEAT_COOL: "auto",
}
BOSCH_TO_HA_STATE = {v: k for k, v in HA_STATE_TO_BOSCH.items()}


_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the BoschTT device."""


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the BoschTT device from config entry."""
    config = entry.data
    websession = async_get_clientsession(hass)
    store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
    token_info = await store.async_load()

    oauth = pyboschtt.BoschTTOAuth(
        config[CONF_CLIENT_ID],
        config[CONF_CLIENT_SECRET],
        websession,
    )

    try:
        token_info = await oauth.refresh_access_token(token_info)
    except pyboschtt.BoschTTOauthError:
        token_info = None

    if not token_info:
        _LOGGER.error("Failed to refresh access token")
        return

    await store.async_save(token_info)

    data_connection = pyboschtt.BoschTTConnection(
        oauth, token_info=token_info, websession=websession
    )

    if not await data_connection.find_devices():
        _LOGGER.error("No devices found")
        return

    tasks = []
    for heater in data_connection.get_devices():
        tasks.append(asyncio.create_task(heater.discover()))
    await asyncio.wait(tasks)

    devs = []
    for heater in data_connection.get_devices():
        devs.append(BoschTTEntity(heater, store))

    async_add_entities(devs, True)


class BoschTTEntity(ClimateEntity):
    """Representation of a BoschTT Thermostat device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    _attr_hvac_modes = [
        HVACMode.HEAT,
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.AUTO,
        HVACMode.FAN_ONLY,
    ]
    _attr_fan_modes = []
    _attr_swing_modes = [SWING_OFF]
    _attr_swing_mode = SWING_OFF

    def __init__(self, heater, store):
        """Initialize the thermostat."""
        self._heater = heater
        self._store = store
        self._attr_unique_id = heater.device_id
        self._attr_name = heater.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Bosch",
            name=self.name,
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._async_refresh_token()
        await self._heater.set_target_temperature(temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        await self._async_refresh_token()
        if hvac_mode == HVACMode.OFF:
            await self._heater.turn_off()
            return

        bosch_mode = HA_STATE_TO_BOSCH.get(hvac_mode)
        if bosch_mode:
            await self._heater.set_value("/airConditioning/operationMode", bosch_mode)

            if await self._heater.is_turned_off():
                await self._heater.turn_on()

        self._attr_hvac_mode = hvac_mode

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._async_refresh_token()
        await self._heater.set_value("/airConditioning/fanSpeed", fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._async_refresh_token()
        res = re.search(r"H: (\S+), V: (\S+)", swing_mode)
        if res:
            await self._heater.set_value(
                "/airConditioning/airFlowHorizontal", res.group(1)
            )
            await self._heater.set_value(
                "/airConditioning/airFlowVertical", res.group(2)
            )

    async def _async_refresh_token(self) -> None:
        try:
            token_info = await self._heater.control.refresh_access_token()
        except pyboschtt.BoschTTOauthError:
            _LOGGER.error("Failed to refresh access token")
            return

        if token_info:
            await self._store.async_save(token_info)

    async def async_update(self) -> None:
        """Retrieve latest state."""
        await self._async_refresh_token()

        op_mode = None
        op_modes = [HVACMode.OFF]
        ac_control = None
        allowed_values_airflow_horizontal = []
        allowed_values_airflow_vertical = []
        airflow_horizontal = None
        airflow_vertical = None
        for resource in await self._heater.get_resources():
            if resource["id"] == "/airConditioning/operationMode":
                op_mode = resource["value"]
                op_modes.extend(resource["allowedValues"])
            elif resource["id"] == "/airConditioning/acControl":
                ac_control = resource["value"]
            elif resource["id"] == "/airConditioning/fanSpeed":
                self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
                self._attr_fan_modes = resource["allowedValues"]
                self._attr_fan_mode = resource["value"]
            elif resource["id"] == "/airConditioning/airFlowHorizontal":
                allowed_values_airflow_horizontal = resource["allowedValues"]
                airflow_horizontal = resource["value"]
            elif resource["id"] == "/airConditioning/airFlowVertical":
                allowed_values_airflow_vertical = resource["allowedValues"]
                airflow_vertical = resource["value"]
            elif resource["id"] == "/airConditioning/temperatureSetpoint":
                self._attr_min_temp = resource["minValue"]
                self._attr_max_temp = resource["maxValue"]
                self._attr_target_temperature = resource["value"]
            elif resource["id"] == "/airConditioning/roomTemperature":
                self._attr_current_temperature = resource["value"]

        swing_modes = []
        for horiz_mode in allowed_values_airflow_horizontal:
            for vertical_mode in allowed_values_airflow_vertical:
                swing_modes.append(f"H: {horiz_mode}, V: {vertical_mode}")
        self._attr_swing_modes = swing_modes
        if swing_modes:
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_mode = f"H: {airflow_horizontal}, V: {airflow_vertical}"

        self._attr_hvac_modes = [
            BOSCH_TO_HA_STATE.get(x) or x for x in op_modes]
        if ac_control == "off":
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = BOSCH_TO_HA_STATE.get(op_mode)
