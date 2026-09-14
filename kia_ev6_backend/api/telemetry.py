import json
import frappe
from frappe import _
from frappe.utils import now_datetime

# Threshold to protect the 12V auxiliary battery.
# When traction battery (HV) is below 20%, the ICCU/LDC suspends auxiliary 12V charging.
# Waking up vehicle ECUs and modem at <20% SOC risks severe 12V battery depletion.
MIN_SAFE_SOC_PERCENT = 20.0
CACHE_EXPIRY_SECONDS = 300  # 5 minutes cache for standard reads


def _get_cache_key(vin: str) -> str:
    return f"ev6_telemetry_cache:{vin}"


def _format_vehicle_state(vehicle) -> dict:
    """Standardizes vehicle document/cache to clean JSON response with dynamic trim & color."""
    trim = vehicle.trim if hasattr(vehicle, "trim") else vehicle.get("trim", "Wind")
    drivetrain = vehicle.drivetrain if hasattr(vehicle, "drivetrain") else vehicle.get("drivetrain", "AWD")
    model_year = int(vehicle.model_year if hasattr(vehicle, "model_year") else vehicle.get("model_year", 2024))
    vehicle_color = vehicle.vehicle_color if hasattr(vehicle, "vehicle_color") else vehicle.get("vehicle_color", "#CC0000")

    name_parts = ["Kia EV6"]
    if trim:
        name_parts.append(str(trim).strip())
    if drivetrain:
        name_parts.append(str(drivetrain).strip())
    formatted_name = " ".join(name_parts)
    raw_name = vehicle.vehicle_name if hasattr(vehicle, "vehicle_name") else vehicle.get("vehicle_name")
    vehicle_name = raw_name if (raw_name and raw_name != "Kia EV6") else formatted_name

    return {
        "vin": vehicle.vin if hasattr(vehicle, "vin") else vehicle.get("vin"),
        "vehicle_name": vehicle_name,
        "trim": trim,
        "drivetrain": drivetrain,
        "model_year": model_year,
        "vehicle_color": vehicle_color,
        "is_locked": bool(vehicle.is_locked if hasattr(vehicle, "is_locked") else vehicle.get("is_locked", 1)),
        "is_trunk_open": bool(vehicle.is_trunk_open if hasattr(vehicle, "is_trunk_open") else vehicle.get("is_trunk_open", 0)),
        "is_hood_open": bool(vehicle.is_hood_open if hasattr(vehicle, "is_hood_open") else vehicle.get("is_hood_open", 0)),
        "odometer_km": float(vehicle.odometer_km if hasattr(vehicle, "odometer_km") else vehicle.get("odometer_km", 0.0)),
        "last_updated": str(vehicle.modified if hasattr(vehicle, "modified") else vehicle.get("last_updated", now_datetime())),
        "battery": {
            "state_of_charge": float(vehicle.state_of_charge if hasattr(vehicle, "state_of_charge") else vehicle.get("state_of_charge", 0.0)),
            "remaining_range_km": float(vehicle.remaining_range_km if hasattr(vehicle, "remaining_range_km") else vehicle.get("remaining_range_km", 0.0)),
            "is_charging": bool(vehicle.is_charging if hasattr(vehicle, "is_charging") else vehicle.get("is_charging", 0)),
            "is_plugged_in": bool(vehicle.is_plugged_in if hasattr(vehicle, "is_plugged_in") else vehicle.get("is_plugged_in", 0)),
            "charging_power_kw": float(vehicle.charging_power_kw if hasattr(vehicle, "charging_power_kw") else vehicle.get("charging_power_kw", 0.0)),
            "target_soc_limit": int(vehicle.target_soc_limit if hasattr(vehicle, "target_soc_limit") else vehicle.get("target_soc_limit", 80)),
        },
        "climate": {
            "is_climate_on": bool(vehicle.is_climate_on if hasattr(vehicle, "is_climate_on") else vehicle.get("is_climate_on", 0)),
            "target_temperature": float(vehicle.target_temperature if hasattr(vehicle, "target_temperature") else vehicle.get("target_temperature", 21.5)),
            "is_defrost_on": bool(vehicle.is_defrost_on if hasattr(vehicle, "is_defrost_on") else vehicle.get("is_defrost_on", 0)),
            "is_steering_heater_on": bool(vehicle.is_steering_heater_on if hasattr(vehicle, "is_steering_heater_on") else vehicle.get("is_steering_heater_on", 0)),
            "seat_heating_level": int(vehicle.seat_heating_level if hasattr(vehicle, "seat_heating_level") else vehicle.get("seat_heating_level", 0)),
        },
    }


def get_cached_telemetry(vin: str) -> dict:
    """Reads cached state from Redis or cached DocType to avoid waking up the vehicle."""
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

    # Fallback to Frappe document cache (DB without external vehicle call)
    vehicle = frappe.get_cached_doc("EV6 Vehicle", vin)
    state = _format_vehicle_state(vehicle)

    # Populate cache
    cache.set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state


def is_vehicle_wake_suspended(state_of_charge: float) -> bool:
    """Returns True if vehicle wake-up must be suspended to protect 12V battery."""
    return state_of_charge < MIN_SAFE_SOC_PERCENT


@frappe.whitelist()
def get_vehicle_telemetry(vin: str, force_refresh: bool = False) -> dict:
    """
    Standard status check endpoint.
    By default (force_refresh=False), returns cached state without vehicle wake-up.
    If force_refresh=True, checks SOC first. If SOC < 20%, wake-up is suspended.
    """
    cached_state = get_cached_telemetry(vin)
    current_soc = cached_state.get("battery", {}).get("state_of_charge", 0.0)

    # Standard read uses cached state without vehicle wake-up
    if not force_refresh:
        return {
            "status": "cached",
            "wake_up_suspended": is_vehicle_wake_suspended(current_soc),
            "data": cached_state,
        }

    # Forced refresh requested: Check if wake-up must be suspended
    if is_vehicle_wake_suspended(current_soc):
        frappe.logger("kia_ev6").warning(
            f"Forced refresh suspended for vehicle {vin}. "
            f"HV SOC is {current_soc}% (< {MIN_SAFE_SOC_PERCENT}%). 12V protection engaged."
        )
        return {
            "status": "wake_up_suspended",
            "wake_up_suspended": True,
            "protection_reason": (
                f"Vehicle wake-up suspended: Traction battery SOC is {current_soc:.1f}% "
                f"(below safety threshold {MIN_SAFE_SOC_PERCENT}%). "
                "Suspended to protect the 12V auxiliary battery from discharge."
            ),
            "data": cached_state,
        }

    # SOC is safe (>= 20%): Proceed with live vehicle wake-up / cloud API refresh
    refreshed_state = _perform_live_vehicle_poll(vin)
    return {
        "status": "refreshed",
        "wake_up_suspended": False,
        "data": refreshed_state,
    }


def _perform_live_vehicle_poll(vin: str) -> dict:
    """Performs live telematics call, logs telemetry, and updates local cache."""
    frappe.logger("kia_ev6").info(f"Initiating live telematics poll for vehicle {vin}")
    vehicle = frappe.get_doc("EV6 Vehicle", vin)

    # In production, this invokes the Kia Connect / Hyundai BlueLink telematics gateway.
    # Here, we update the timestamp and synchronize current state.
    state = _format_vehicle_state(vehicle)

    # Write to EV6 Telemetry Log for audit and historical graphs
    log_telemetry(
        vin=vin,
        state_of_charge=vehicle.state_of_charge,
        remaining_range_km=vehicle.remaining_range_km,
        is_charging=vehicle.is_charging,
        charging_power_kw=vehicle.charging_power_kw,
    )

    # Update cache
    frappe.cache().set_value(_get_cache_key(vin), json.dumps(state), expires_in_sec=CACHE_EXPIRY_SECONDS)
    return state


@frappe.whitelist()
def log_telemetry(vin: str, state_of_charge: float, remaining_range_km: float, is_charging: bool = False, charging_power_kw: float = 0.0):
    """Logs a telemetry entry into EV6 Telemetry Log and updates master document."""
    log = frappe.get_doc({
        "doctype": "EV6 Telemetry Log",
        "vehicle": vin,
        "timestamp": now_datetime(),
        "state_of_charge": float(state_of_charge),
        "remaining_range_km": float(remaining_range_km),
        "is_charging": 1 if is_charging else 0,
        "charging_power_kw": float(charging_power_kw),
    })
    log.insert(ignore_permissions=True)

    # Update master vehicle document
    frappe.db.set_value("EV6 Vehicle", vin, {
        "state_of_charge": float(state_of_charge),
        "remaining_range_km": float(remaining_range_km),
        "is_charging": 1 if is_charging else 0,
        "charging_power_kw": float(charging_power_kw),
    })

    # Invalidate cache so subsequent reads reflect new telemetry
    frappe.cache().delete_value(_get_cache_key(vin))
    return {"status": "logged", "log_id": log.name}


def poll_vehicles_telemetry():
    """
    Background cron job to poll vehicles.
    Safely suspends wake-up for any vehicle with SOC < 20% to prevent 12V battery death.
    """
    logger = frappe.logger("kia_ev6")
    vehicles = frappe.get_all("EV6 Vehicle", fields=["name", "vin", "state_of_charge", "is_charging"])

    for v in vehicles:
        soc = float(v.state_of_charge or 0.0)

        # 12V Battery Protection Check
        if is_vehicle_wake_suspended(soc):
            logger.warning(
                f"[Scheduler] Skipping telemetry wake-up for vehicle {v.vin}: "
                f"SOC is {soc}% (< {MIN_SAFE_SOC_PERCENT}%). 12V battery protection active."
            )
            continue

        try:
            _perform_live_vehicle_poll(v.vin)
            logger.info(f"[Scheduler] Polled telemetry for vehicle {v.vin} successfully.")
        except Exception as e:
            logger.error(f"[Scheduler] Failed to poll vehicle {v.vin}: {str(e)}")
