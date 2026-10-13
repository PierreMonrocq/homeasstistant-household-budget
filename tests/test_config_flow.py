"""Tests for the household budget config flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.household_budget.const import DOMAIN


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """A filled-in form creates a config entry for the household."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Our Household", "currency": "EUR"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Our Household"
    assert result["data"] == {"name": "Our Household", "currency": "EUR"}


async def test_user_flow_duplicate_name_aborts(hass: HomeAssistant) -> None:
    """Creating a second household with the same name aborts."""
    data = {"name": "Our Household", "currency": "EUR"}

    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(first["flow_id"], data)
    await hass.async_block_till_done()

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(second["flow_id"], data)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
