import json
import frappe
from frappe import _
from frappe.utils import now_datetime

# Safety Threshold to protect 12V auxiliary battery
MIN_SAFE_SOC_PERCENT = 20.0
CACHE_EXPIRY_SECONDS = 300  # 5-minute Redis cache TTL


# ==========================================
# NULL-SAFE TYPE CASTING HELPERS
# ==========================================

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


# ==========================================
# DYNAMIC VEHICLE DOCUMENT RESOLUTION
# ==========================================

def _get_vehicle_doc(vin: str = None):
    """
    Resolves the EV6 Vehicle document safely.
    Checks primary key 'name', matching 'vin' field, user ownership, or fallback.
    """
    if not vin:
        user = frappe.session.user
        vin = frappe.db.get_value("EV6 Vehicle", {"owner": user}, "vin") or frappe.db.get_value("EV6 Vehicle", {"owner": user}, "name")
        if not vin:
            vin = frappe.db.get_value("EV6 Vehicle", {}, "name")

    if not vin:
        frappe.throw(_("No EV6 Vehicle record found in system."), frappe.DoesNotExistError)

    # 1. Primary key match
    if frappe.db.exists("EV6 Vehicle", vin):
        return frappe.get_doc("EV6 Vehicle", vin)

    # 2. 'vin' field match
    doc_name = frappe.db.get_value("EV6 Vehicle", {"vin": vin}, "name")
    if doc_name:
        return frappe.get_doc("EV6 Vehicle", doc_name)

    # 3. Fallback to first available record in system
    first_record = frappe.db.get_value("EV6 Vehicle", {}, "name")
    if first_record:
        return frappe.get_doc("EV6 Vehicle", first_record)

    frappe.throw(_(f"EV6 Vehicle record for identifier '{vin}' not found."), frappe.DoesNotExistError)


# ==========================================
# STATE FORMATTER & REDIS CACHING
# ==========================================

def _format_vehicle_state(vehicle) -> dict:
    """Standardizes vehicle document into clean, null-safe JSON telemetry output."""
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
    """Reads cached state from Redis or falls back safely to DB."""
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
    """Returns True if vehicle wake-up must be suspended to protect 12V battery."""
    return state_of_charge < MIN_SAFE_SOC_PERCENT


# ==========================================
# WHITELISTED API ENDPOINTS
# ==========================================

@frappe.whitelist()
def get_vehicle_telemetry(vin: str = None, force_refresh: bool = False) -> dict:
    """Main client endpoint called by Flutter app."""
    vehicle_doc = _get_vehicle_doc(vin)
    resolved_vin = vehicle_doc.vin or vehicle_doc.name

    cached_state = get_cached_telemetry(resolved_vin)
    current_soc = cached_state.get("battery", {}).get("state_of_charge", 0.0)

    if not force_refresh:
        return {
            "status": "cached",
            "wake_up_suspended": is_vehicle_wake_suspended(current_soc),
            "data": cached_state,
        }

    if is_vehicle_wake_suspended(current_soc):
        return {
            "status": "wake_up_suspended",
            "wake_up_suspended": True,
            "protection_reason": f"Wake-up suspended: HV SOC {current_soc:.1f}% < {MIN_SAFE_SOC_PERCENT}%.",
            "data": cached_state,
        }

    refreshed_state = _perform_live_vehicle_poll(resolved_vin)
    return {
        "status": "refreshed",
        "wake_up_suspended": False,
        "data": refreshed_state,
    }


@frappe.whitelist(allow_guest=True)
def ingest_hardware_telemetry():
    """
    HTTP POST endpoint targeted by hardware dongle (ESP32 / OVMS) or manual cURL tests.
    Updates vehicle telemetry records dynamically.
    """
    data = frappe.request.get_json() or {}
    vin = data.get("vin")

    if not vin:
        frappe.throw(_("Missing VIN parameter."), frappe.ValidationError)

    vehicle_doc = _get_vehicle_doc(vin)

    if "soc" in data or "state_of_charge" in data:
        vehicle_doc.state_of_charge = _safe_float(data.get("soc", data.get("state_of_charge")))
    if "range_km" in data or "remaining_range_km" in data:
        vehicle_doc.remaining_range_km = _safe_float(data.get("range_km", data.get("remaining_range_km")))
    if "is_charging" in data:
        vehicle_doc.is_charging = 1 if data["is_charging"] else 0
    if "is_plugged_in" in data:
        vehicle_doc.is_plugged_in = 1 if data["is_plugged_in"] else 0
    if "is_locked" in data:
        vehicle_doc.is_locked = 1 if data["is_locked"] else 0
    if "odometer_km" in data:
        vehicle_doc.odometer_km = _safe_float(data["odometer_km"])
    if "target_temperature" in data:
        vehicle_doc.target_temperature = _safe_float(data["target_temperature"])
    if "target_soc_limit" in data:
        vehicle_doc.target_soc_limit = _safe_int(data["target_soc_limit"])

    vehicle_doc.save(ignore_permissions=True)

    # Invalidate cache so Flutter app gets instant updates
    frappe.cache().delete_value(_get_cache_key(vehicle_doc.vin or vehicle_doc.name))

    return {"status": "success", "vin": vehicle_doc.vin or vehicle_doc.name}


import frappe
from frappe import _

@frappe.whitelist()
def pair_hardware(vin: str, hardware_serial: str) -> dict:
    """
    Pairs a physical OBD-II telematics dongle (scanned via QR code)
    with an EV6 Vehicle record owned by the authenticated user.
    """
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Authentication required to pair vehicle hardware."), frappe.AuthenticationError)

    vin = vin.strip()
    hardware_serial = hardware_serial.strip()

    if not vin or not hardware_serial:
        frappe.throw(_("Both VIN and Hardware Serial are required for pairing."), frappe.ValidationError)

    # Verify vehicle ownership
    doc_name = frappe.db.get_value("EV6 Vehicle", {"vin": vin, "owner": user}, "name")
    if not doc_name and "System Manager" in frappe.get_roles(user):
        doc_name = frappe.db.get_value("EV6 Vehicle", {"vin": vin}, "name")

    if not doc_name:
        frappe.throw(_(f"Vehicle with VIN '{vin}' not found or not owned by account '{user}'."), frappe.DoesNotExistError)

    # Assign hardware serial to vehicle record
    doc = frappe.get_doc("EV6 Vehicle", doc_name)
    doc.db_set("hardware_serial", hardware_serial, commit=True)

    # Invalidate cache
    frappe.cache().delete_value(f"ev6_telemetry_cache:{vin}")

    return {
        "status": "success",
        "message": "Hardware successfully paired with EV6 Vehicle.",
        "vin": vin,
        "hardware_serial": hardware_serial
    }
@frappe.whitelist()
def log_telemetry(vin: str, state_of_charge: float, remaining_range_km: float, is_charging: bool = False, charging_power_kw: float = 0.0):
    """Logs a entry into EV6 Telemetry Log DocType for historical graphs."""
    vehicle_doc = _get_vehicle_doc(vin)
    resolved_vin = vehicle_doc.name

    log = frappe.get_doc({
        "doctype": "EV6 Telemetry Log",
        "vehicle": resolved_vin,
        "timestamp": now_datetime(),
        "state_of_charge": _safe_float(state_of_charge),
        "remaining_range_km": _safe_float(remaining_range_km),
        "is_charging": 1 if is_charging else 0,
        "charging_power_kw": _safe_float(charging_power_kw),
    })
    log.insert(ignore_permissions=True)

    frappe.db.set_value("EV6 Vehicle", resolved_vin, {
        "state_of_charge": _safe_float(state_of_charge),
        "remaining_range_km": _safe_float(remaining_range_km),
        "is_charging": 1 if is_charging else 0,
        "charging_power_kw": _safe_float(charging_power_kw),
    })

    frappe.cache().delete_value(_get_cache_key(resolved_vin))
    return {"status": "logged", "log_id": log.name}


def _perform_live_vehicle_poll(vin: str) -> dict:
    vehicle = _get_vehicle_doc(vin)
    state = _format_vehicle_state(vehicle)
    frappe.cache().set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state


def poll_vehicles_telemetry():
    """Background cron job task."""
    logger = frappe.logger("kia_ev6")
    vehicles = frappe.get_all("EV6 Vehicle", fields=["name", "vin", "state_of_charge"])

    for v in vehicles:
        soc = _safe_float(v.get("state_of_charge"))
        if is_vehicle_wake_suspended(soc):
            logger.warning(f"[Scheduler] Skipping telemetry poll for vehicle {v.name}: SOC is {soc}%.")
            continue
        try:
            _perform_live_vehicle_poll(v.name)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to poll vehicle {v.name}: {str(e)}")
