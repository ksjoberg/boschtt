"""Config flow for BoschTT."""
import logging

import pyboschtt

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

import voluptuous as vol

from .const import (
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

DATA_BOSCHTT_IMPL = "boschtt_flow_implementation"

_LOGGER = logging.getLogger(__name__)


@callback
def register_flow_implementation(hass, client_id, client_secret):
    """Register a boschtt implementation.

    client_id: Client id.
    client_secret: Client secret.
    """
    hass.data.setdefault(DATA_BOSCHTT_IMPL, {})

    hass.data[DATA_BOSCHTT_IMPL] = {
        CONF_CLIENT_ID: client_id,
        CONF_CLIENT_SECRET: client_secret,
    }


class BoschTTFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize flow."""
        self._oauth = None

    async def async_step_user(self, user_input=None):
        """Handle external yaml configuration."""
        self._async_abort_entries_match()

        config = self.hass.data.get(DATA_BOSCHTT_IMPL, {})

        if not config:
            _LOGGER.debug("No config")
            return self.async_abort(reason="missing_configuration")

        return await self.async_step_auth()

    async def async_step_auth(self, user_input=None):
        """Handle a flow start."""
        self._async_abort_entries_match()

        errors = {}

        if user_input is not None:
            oauth = self._generate_oauth()
            token_info = await oauth.authenticate(
                user_input["username"], user_input["password"]
            )
            store = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)
            await store.async_save(token_info)

            config = self.hass.data[DATA_BOSCHTT_IMPL].copy()
            return self.async_create_entry(title="BoschTT", data=config)

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                }
            ),
            description_placeholders={},
            errors=errors,
        )

    def _generate_oauth(self):
        config = self.hass.data[DATA_BOSCHTT_IMPL]
        clientsession = async_get_clientsession(self.hass)

        return pyboschtt.BoschTTOAuth(
            config.get(CONF_CLIENT_ID),
            config.get(CONF_CLIENT_SECRET),
            clientsession,
        )
