import json
import frappe
from frappe import _
from frappe.utils import now_datetime

MIN_SAFE_SOC_PERCENT = 20.0
CACHE_EXPIRY_SECONDS = 300

def _safe_float(val, default=0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def _safe_int(val, default=0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def _safe_bool(val, default=False) -> bool:
    if val is None:
        return default
    return bool(val)

def _get_field(doc, fieldname, default=None):
    if hasattr(doc, fieldname):
        val = getattr(doc, fieldname)
        if val is not None:
            return val
    if isinstance(doc, dict) and fieldname in doc:
        val = doc[fieldname]
        if val is not None:
            return val
    return default

def _get_cache_key(vin: str) -> str:
    return f"ev6_telemetry_cache:{vin}"

def _get_vehicle_doc(vin: str):
    if not vin:
        user = frappe.session.user
        vin = frappe.db.get_value("EV6 Vehicle", {"owner": user}, "vin") or frappe.db.get_value("EV6 Vehicle", {"owner": user}, "name")
        if not vin:
            vin = frappe.db.get_value("EV6 Vehicle", {}, "name")

    if not vin:
        frappe.throw(_("No EV6 Vehicle record found in system."), frappe.DoesNotExistError)

    if frappe.db.exists("EV6 Vehicle", vin):
        return frappe.get_doc("EV6 Vehicle", vin)

    doc_name = frappe.db.get_value("EV6 Vehicle", {"vin": vin}, "name")
    if doc_name:
        return frappe.get_doc("EV6 Vehicle", doc_name)

    first_record = frappe.db.get_value("EV6 Vehicle", {}, "name")
    if first_record:
        return frappe.get_doc("EV6 Vehicle", first_record)

    frappe.throw(_(f"EV6 Vehicle record '{vin}' not found."), frappe.DoesNotExistError)

def _format_vehicle_state(vehicle) -> dict:
    resolved_vin = _get_field(vehicle, "vin", _get_field(vehicle, "name", ""))
    trim = _get_field(vehicle, "trim", "Wind")
    drivetrain = _get_field(vehicle, "drivetrain", "AWD")
    model_year = _safe_int(_get_field(vehicle, "model_year"), 2024)
    vehicle_color = _get_field(vehicle, "vehicle_color", "#CC0000")

    name_parts = ["Kia EV6"]
    if trim:
        name_parts.append(str(trim).strip())
    if drivetrain:
        name_parts.append(str(drivetrain).strip())
    formatted_name = " ".join(name_parts)
    raw_name = _get_field(vehicle, "vehicle_name")
    vehicle_name = raw_name if (raw_name and raw_name != "Kia EV6") else formatted_name

    return {
        "vin": resolved_vin,
        "vehicle_name": vehicle_name,
        "trim": trim,
        "drivetrain": drivetrain,
        "model_year": model_year,
        "vehicle_color": vehicle_color,
        "vehicle_color_hex": vehicle_color,
        "is_locked": _safe_bool(_get_field(vehicle, "is_locked"), True),
        "is_trunk_open": _safe_bool(_get_field(vehicle, "is_trunk_open"), False),
        "is_hood_open": _safe_bool(_get_field(vehicle, "is_hood_open"), False),
        "odometer_km": _safe_float(_get_field(vehicle, "odometer_km"), 0.0),
        "last_updated": str(_get_field(vehicle, "modified", now_datetime())),
        "battery": {
            "state_of_charge": _safe_float(_get_field(vehicle, "state_of_charge"), 0.0),
            "remaining_range_km": _safe_float(_get_field(vehicle, "remaining_range_km"), 0.0),
            "is_charging": _safe_bool(_get_field(vehicle, "is_charging"), False),
            "is_plugged_in": _safe_bool(_get_field(vehicle, "is_plugged_in"), False),
            "charging_power_kw": _safe_float(_get_field(vehicle, "charging_power_kw"), 0.0),
            "target_soc_limit": _safe_int(_get_field(vehicle, "target_soc_limit"), 80),
        },
        "climate": {
            "is_climate_on": _safe_bool(_get_field(vehicle, "is_climate_on"), False),
            "target_temperature": _safe_float(_get_field(vehicle, "target_temperature"), 21.5),
            "is_defrost_on": _safe_bool(_get_field(vehicle, "is_defrost_on"), False),
            "is_steering_heater_on": _safe_bool(_get_field(vehicle, "is_steering_heater_on"), False),
            "seat_heating_level": _safe_int(_get_field(vehicle, "seat_heating_level"), 0),
        },
    }

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

    vehicle = _get_vehicle_doc(vin)
    state = _format_vehicle_state(vehicle)
    cache.set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state

def is_vehicle_wake_suspended(state_of_charge: float) -> bool:
    return state_of_charge < MIN_SAFE_SOC_PERCENT

@frappe.whitelist()
def get_vehicle_telemetry(vin: str = None, force_refresh: bool = False) -> dict:
    vehicle_doc = _get_vehicle_doc(vin)
    resolved_vin = vehicle_doc.vin or vehicle_doc.name

    cached_state = get_cached_telemetry(resolved_vin)
    current_soc = cached_state.get("battery", {}).get("state_of_charge", 0.0)

    return {
        "status": "cached",
        "wake_up_suspended": is_vehicle_wake_suspended(current_soc),
        "data": cached_state,
    }
