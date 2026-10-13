"""Constants for the Household Budget integration."""

from __future__ import annotations

DOMAIN = "household_budget"

CONF_NAME = "name"
CONF_CURRENCY = "currency"

DEFAULT_CURRENCY = "EUR"

# Bumped to 2 when buckets became sliding windows: adjustments and budget
# history were dropped from the schema.
STORAGE_VERSION = 2

SUBENTRY_TYPE_BUCKET = "bucket"

VISIBILITY_SHARED = "shared"
VISIBILITY_PERSONAL = "personal"
VISIBILITY_OPTIONS = [VISIBILITY_SHARED, VISIBILITY_PERSONAL]

DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 3650
MAX_DESCRIPTION_LENGTH = 255
MAX_LIMIT_MAJOR_UNITS = 1_000_000

SERVICE_ADD_EXPENSE = "add_expense"
SERVICE_EDIT_EXPENSE = "edit_expense"
SERVICE_DELETE_EXPENSE = "delete_expense"
SERVICE_LIST_EXPENSES = "list_expenses"

EVENT_EXPENSE_ADDED = f"{DOMAIN}_expense_added"
EVENT_EXPENSE_EDITED = f"{DOMAIN}_expense_edited"
EVENT_EXPENSE_DELETED = f"{DOMAIN}_expense_deleted"
EVENT_THRESHOLD_CROSSED = f"{DOMAIN}_threshold_crossed"
EVENT_OVERSPENT = f"{DOMAIN}_overspent"

# Panels subscribe to this rather than to a coordinator, because writing a
# bucket reloads the config entry and replaces the coordinator object. A
# dispatcher signal is a string, so it survives that.
SIGNAL_BUCKETS_UPDATED = f"{DOMAIN}_buckets_updated"

ATTR_AMOUNT = "amount"
ATTR_BUCKET_ID = "bucket_id"
ATTR_DATE = "date"
ATTR_DATE_FROM = "date_from"
ATTR_DATE_TO = "date_to"
ATTR_DESCRIPTION = "description"
ATTR_EXPENSE_ID = "expense_id"
ATTR_LIMIT = "limit"

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 500

# The management panel is served by the integration and registered in the
# sidebar, the way the Energy panel is. Bumping the version busts the
# browser cache after an update.
PANEL_FILENAME = "household-budget-panel.js"
PANEL_VERSION = "13"
PANEL_STATIC_PATH = f"/{DOMAIN}/{PANEL_FILENAME}"
PANEL_MODULE_URL = f"{PANEL_STATIC_PATH}?v={PANEL_VERSION}"
PANEL_URL_PATH = "household-budget"
PANEL_COMPONENT_NAME = "household-budget-panel"
PANEL_ICON = "mdi:wallet"
# Home Assistant does not translate a custom panel's sidebar title — it is
# shown verbatim. Users can also rename a sidebar entry themselves by editing
# the sidebar.
PANEL_SIDEBAR_TITLE = "Gestion du Budget"
