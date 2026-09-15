import json
import frappe
from frappe import _
from hyundai_kia_connect_api import VehicleManager, Region, Brand
from .telemetry import (
    MIN_SAFE_SOC_PERCENT,
    is_vehicle_wake_suspended,
    get_cached_telemetry,
    _get_cache_key,
)

WAKE_REQUIRING_COMMANDS = {
    "start_climate", "stop_climate", "set_climate", "lock_doors",
    "unlock_doors", "open_trunk", "start_charge", "stop_charge",
    "open_tailgate", "close_tailgate", "vent_windows", "close_windows", "prep_rspa_mode"
}

def get_vehicle_manager() -> VehicleManager:
    username = frappe.db.get_single_value("Kia Connect Settings", "username")
    password = frappe.db.get_single_value("Kia Connect Settings", "password")
    pin = frappe.db.get_single_value("Kia Connect Settings", "pin")
    return VehicleManager(region=Region.EUROPE, brand=Brand.KIA, username=username, password=password, pin=pin)

@frappe.whitelist()
def execute_command(vin: str, command: str, parameters=None) -> dict:
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except Exception:
            parameters = {}
    parameters = parameters or {}

    cached_state = get_cached_telemetry(vin)
    current_soc = float(cached_state.get("battery", {}).get("state_of_charge", 0.0))
    is_plugged_in = bool(cached_state.get("battery", {}).get("is_plugged_in", False))

    if command in WAKE_REQUIRING_COMMANDS and is_vehicle_wake_suspended(current_soc):
        if not (command == "start_charge" and is_plugged_in):
            frappe.throw(_("Vehicle wake-up suspended to prevent 12V drain."), frappe.ValidationError)

    vm = get_vehicle_manager()
    vm.check_and_refresh_token()
    vehicle = frappe.get_doc("EV6 Vehicle", vin)

    # API Dispatch
    if command == "lock_doors":
        vm.lock(vin)
        vehicle.is_locked = 1
    elif command == "unlock_doors":
        vm.unlock(vin)
        vehicle.is_locked = 0
    elif command == "start_climate":
        target = float(parameters.get("target_temperature", 21.5))
        vm.start_climate(vin, set_temp=target)
        vehicle.is_climate_on = 1
        vehicle.target_temperature = target
    elif command == "stop_climate":
        vm.stop_climate(vin)
        vehicle.is_climate_on = 0
    elif command == "start_charge":
        vm.start_charge(vin)
        vehicle.is_charging = 1
    elif command == "stop_charge":
        vm.stop_charge(vin)
        vehicle.is_charging = 0
    elif command == "set_charging_limit":
        limit = int(parameters.get("target_soc_limit", 80))
        vm.set_charge_limits(vin, ac=limit, dc=limit)
        vehicle.target_soc_limit = limit

    vehicle.save(ignore_permissions=True)
    frappe.cache().delete_value(_get_cache_key(vin))

    return {
        "status": "success",
        "command": command,
        "vin": vin,
        "parameters": parameters,
    }
