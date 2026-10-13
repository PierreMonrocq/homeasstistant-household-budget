"""The Household Budget integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .buckets import bucket_has_records, subentry_for_bucket
from .const import (
    CONF_CURRENCY,
    CONF_NAME,
    DOMAIN,
    PANEL_COMPONENT_NAME,
    PANEL_FILENAME,
    PANEL_ICON,
    PANEL_MODULE_URL,
    PANEL_SIDEBAR_TITLE,
    PANEL_STATIC_PATH,
    PANEL_URL_PATH,
)
from .coordinator import HouseholdBudgetCoordinator
from .services import async_setup_services
from .store import HouseholdBudgetStore
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.NUMBER, Platform.SENSOR]


@dataclass
class HouseholdBudgetData:
    """Runtime data attached to the config entry (`entry.runtime_data`)."""

    name: str
    currency: str
    store: HouseholdBudgetStore
    coordinator: HouseholdBudgetCoordinator


type HouseholdBudgetConfigEntry = ConfigEntry[HouseholdBudgetData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register what is global to the integration rather than per-household.

    The management panel is served from the integration itself and registered
    in the sidebar, the way the Energy panel is — so there is nothing for the
    user to install, and no second HACS repository, since a repository can
    only be one category.
    """
    async_setup_services(hass)
    async_setup_websocket_api(hass)
    await _async_register_panel(hass)
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel's JavaScript and add it to the sidebar.

    `frontend` is an `after_dependencies`, not a hard one: the integration is
    perfectly usable through its sensors and actions on a headless instance,
    and a hard dependency would also mean the test environment had to ship the
    compiled frontend. When it is absent, the panel is simply not registered.
    """
    panel_file = Path(__file__).parent / "www" / PANEL_FILENAME
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_PATH, str(panel_file), cache_headers=False)]
        )
    except RuntimeError:
        # The web server freezes its router once it is listening, so a route
        # can only be added during start-up. Everything else — sensors,
        # actions, websocket commands — works regardless; only the panel
        # needs a restart to be served.
        _LOGGER.warning(
            "Could not register the budget panel at %s because Home Assistant "
            "is already running. Restart Home Assistant to use it",
            PANEL_STATIC_PATH,
        )
        return

    if "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; skipping panel registration")
        return

    # The version query string only goes on the module URL: a static route
    # must be a plain path.
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT_NAME,
        module_url=PANEL_MODULE_URL,
        sidebar_title=PANEL_SIDEBAR_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        embed_iframe=False,
    )


async def async_setup_entry(hass: HomeAssistant, entry: HouseholdBudgetConfigEntry) -> bool:
    """Set up a household budget config entry."""
    store = HouseholdBudgetStore(hass, entry.entry_id)
    await store.async_load()

    coordinator = HouseholdBudgetCoordinator(hass, entry)
    entry.runtime_data = HouseholdBudgetData(
        name=entry.data[CONF_NAME],
        currency=entry.data[CONF_CURRENCY],
        store=store,
        coordinator=coordinator,
    )

    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_midnight_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HouseholdBudgetConfigEntry) -> bool:
    """Unload a household budget config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: HouseholdBudgetConfigEntry) -> None:
    """Reload when a bucket is added, edited or archived.

    Buckets live in config subentries, so adding one or changing its limit
    through the `number` entity lands here, and the reload rebuilds the
    devices and entities to match.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: HouseholdBudgetConfigEntry, device: DeviceEntry
) -> bool:
    """Let a bucket be deleted from its device page.

    A bucket with expenses is archived rather than deleted, exactly as in the
    config flow: its past expenses stay in the store, but it loses its device
    and entities.
    """
    bucket_ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
    for bucket_id in bucket_ids:
        subentry = subentry_for_bucket(entry, bucket_id)
        if subentry is None:
            continue
        if bucket_has_records(entry.runtime_data.store, bucket_id):
            hass.config_entries.async_update_subentry(
                entry, subentry, data={**subentry.data, "archived": True}
            )
        else:
            hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    return True
