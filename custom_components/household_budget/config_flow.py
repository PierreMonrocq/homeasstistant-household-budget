"""Config flow for the Household Budget integration.

Only the household itself is created here: a name and a currency. Buckets are
not configured through a flow at all — they are created, edited and archived
from the "Gestion du Budget" sidebar panel, which is the single management
interface.

Buckets are still *stored* as config subentries of the household entry; the
panel writes them through the websocket commands in `websocket_api.py`. No
subentry flow is registered, so the integration page cannot offer a second,
drifting way to edit a bucket.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import voluptuous as vol

from .const import CONF_CURRENCY, CONF_NAME, DEFAULT_CURRENCY, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_CURRENCY, default=DEFAULT_CURRENCY): str,
    }
)


class HouseholdBudgetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a household budget."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step: create the household."""
        if user_input is not None:
            self._async_abort_entries_match({CONF_NAME: user_input[CONF_NAME]})
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
