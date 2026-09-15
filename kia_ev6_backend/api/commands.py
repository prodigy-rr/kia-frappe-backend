import json
import frappe
from frappe import _
from .telemetry import (
    MIN_SAFE_SOC_PERCENT,
    is_vehicle_wake_suspended,
    get_cached_telemetry,
    _get_cache_key,
)

# Commands requiring active vehicle state
WAKE_REQUIRING_COMMANDS = {
    "start_climate",
    "stop_climate",
    "set_climate",
    "lock_doors",
    "unlock_doors",
    "open_trunk",
    "start_charge",
    "stop_charge",
    "open_tailgate",
    "close_tailgate",
    "vent_windows",
    "close_windows",
    "prep_rspa_mode",
}

@frappe.whitelist()
def execute_command(vin: str, command: str, parameters=None) -> dict:
    """
    Executes a vehicle command in Frappe.
    Suspends action if high-voltage battery SOC < 20% to protect 12V auxiliary battery.
    """
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except Exception:
            parameters = {}
    parameters = parameters or {}

    # Check cached SOC for 12V battery protection
    cached_state = get_cached_telemetry(vin)
    current_soc = float(cached_state.get("battery", {}).get("state_of_charge", 0.0))
    is_plugged_in = bool(cached_state.get("battery", {}).get("is_plugged_in", False))

    if command in WAKE_REQUIRING_COMMANDS and is_vehicle_wake_suspended(current_soc):
        if command == "start_charge" and is_plugged_in:
            frappe.logger("kia_ev6").info(
                f"Allowing start_charge for {vin} despite SOC {current_soc}% (plugged in)."
            )
        else:
            msg = (
                f"Command '{command}' suspended: "
                f"High-voltage battery SOC is {current_soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%). "
                "12V battery protection active."
            )
            frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
            frappe.throw(_(msg), frappe.ValidationError)

    vehicle = frappe.get_doc("EV6 Vehicle", vin)

    # Process command state updates
    if command == "lock_doors":
        vehicle.is_locked = 1
    elif command == "unlock_doors":
        vehicle.is_locked = 0
    elif command == "start_climate":
        vehicle.is_climate_on = 1
        if "target_temperature" in parameters:
            vehicle.target_temperature = float(parameters["target_temperature"])
    elif command == "stop_climate":
        vehicle.is_climate_on = 0
    elif command == "start_charge":
        vehicle.is_charging = 1
    elif command == "stop_charge":
        vehicle.is_charging = 0

    vehicle.save(ignore_permissions=True)

    # Invalidate Redis cache
    frappe.cache().delete_value(_get_cache_key(vin))

    return {
        "status": "queued",
        "command": command,
        "vin": vin,
        "parameters": parameters,
    }

@frappe.whitelist()
def set_charging_limit(vin: str, target_soc_limit: int) -> dict:
    """Updates target charge limit (50% - 100%)."""
    limit = int(target_soc_limit)
    if limit < 50 or limit > 100:
        frappe.throw(_("Target SOC limit must be between 50% and 100%."))

    frappe.db.set_value("EV6 Vehicle", vin, "target_soc_limit", limit)
    frappe.cache().delete_value(_get_cache_key(vin))

    return {"status": "success", "target_soc_limit": limit}

@frappe.whitelist()
def update_vehicle_profile(vin: str, trim: str = None, drivetrain: str = None, model_year: int = None, vehicle_color: str = None) -> dict:
    """Updates vehicle metadata in Frappe database."""
    vehicle = frappe.get_doc("EV6 Vehicle", vin)
    if trim:
        vehicle.trim = trim
    if drivetrain:
        vehicle.drivetrain = drivetrain
    if model_year:
        vehicle.model_year = int(model_year)
    if vehicle_color:
        vehicle.vehicle_color = vehicle_color

    vehicle.save(ignore_permissions=True)
    frappe.cache().delete_value(_get_cache_key(vin))

    return {
        "status": "success",
        "vin": vin,
        "trim": vehicle.trim,
        "drivetrain": vehicle.drivetrain,
        "model_year": vehicle.model_year,
        "vehicle_color": vehicle.vehicle_color,
    }
