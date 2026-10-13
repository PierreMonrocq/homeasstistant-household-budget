"""Tests for setting up and unloading the household budget integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.household_budget.const import DOMAIN


async def test_setup_and_unload_entry(hass: HomeAssistant) -> None:
    """The entry loads cleanly and unloads cleanly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Our Household",
        data={"name": "Our Household", "currency": "EUR"},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.name == "Our Household"
    assert entry.runtime_data.currency == "EUR"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
