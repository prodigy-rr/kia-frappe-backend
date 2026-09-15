import json
import frappe
from frappe import _
from frappe.utils import now_datetime
from hyundai_kia_connect_api import VehicleManager, Region, Brand

MIN_SAFE_SOC_PERCENT = 20.0
CACHE_EXPIRY_SECONDS = 300

def get_vehicle_manager() -> VehicleManager:
    username = frappe.db.get_single_value("Kia Connect Settings", "username")
    password = frappe.db.get_single_value("Kia Connect Settings", "password")
    pin = frappe.db.get_single_value("Kia Connect Settings", "pin")
    return VehicleManager(region=Region.EUROPE, brand=Brand.KIA, username=username, password=password, pin=pin)

def _get_cache_key(vin: str) -> str:
    return f"ev6_telemetry_cache:{vin}"

def is_vehicle_wake_suspended(state_of_charge: float) -> bool:
    return state_of_charge < MIN_SAFE_SOC_PERCENT

def get_cached_telemetry(vin: str) -> dict:
    cache = frappe.cache()
    cached_data = cache.get_value(_get_cache_key(vin))
    if cached_data:
        if isinstance(cached_data, str):
            try:
                return json.loads(cached_data)
            except Exception:
                pass
        elif isinstance(cached_data, dict):
            return cached_data

    # Fetch from cloud cache without waking the vehicle modem
    vm = get_vehicle_manager()
    vm.check_and_refresh_token()
    vm.update_all_vehicles_with_cached_state()

    live_vehicle = vm.get_vehicle(vin)
    if live_vehicle:
        vehicle = frappe.get_doc("EV6 Vehicle", vin)
        vehicle.state_of_charge = live_vehicle.ev_battery_percentage
        vehicle.remaining_range_km = live_vehicle.ev_driving_range
        vehicle.is_charging = 1 if live_vehicle.ev_battery_is_charging else 0
        vehicle.is_locked = 1 if live_vehicle.is_locked else 0
        vehicle.is_climate_on = 1 if live_vehicle.air_control_is_on else 0
        vehicle.save(ignore_permissions=True)

    vehicle = frappe.get_cached_doc("EV6 Vehicle", vin)
    state = _format_vehicle_state(vehicle) # Assume _format_vehicle_state exists as per your provided code
    cache.set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state

@frappe.whitelist()
def get_vehicle_telemetry(vin: str, force_refresh: bool = False) -> dict:
    cached_state = get_cached_telemetry(vin)
    current_soc = cached_state.get("battery", {}).get("state_of_charge", 0.0)

    if not force_refresh:
        return {"status": "cached", "wake_up_suspended": is_vehicle_wake_suspended(current_soc), "data": cached_state}

    if is_vehicle_wake_suspended(current_soc):
        return {
            "status": "wake_up_suspended",
            "wake_up_suspended": True,
            "data": cached_state,
        }

    refreshed_state = _perform_live_vehicle_poll(vin)
    return {"status": "refreshed", "wake_up_suspended": False, "data": refreshed_state}

def _perform_live_vehicle_poll(vin: str) -> dict:
    frappe.logger("kia_ev6").info(f"Live poll for {vin}")

    vm = get_vehicle_manager()
    vm.check_and_refresh_token()
    vm.force_refresh_vehicle_state(vin) # Physical wake-up

    live_vehicle = vm.get_vehicle(vin)
    vehicle = frappe.get_doc("EV6 Vehicle", vin)
    vehicle.state_of_charge = live_vehicle.ev_battery_percentage
    vehicle.remaining_range_km = live_vehicle.ev_driving_range
    vehicle.is_charging = 1 if live_vehicle.ev_battery_is_charging else 0
    vehicle.is_locked = 1 if live_vehicle.is_locked else 0
    vehicle.is_climate_on = 1 if live_vehicle.air_control_is_on else 0
    vehicle.save(ignore_permissions=True)

    state = _format_vehicle_state(vehicle)
    frappe.cache().set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state
