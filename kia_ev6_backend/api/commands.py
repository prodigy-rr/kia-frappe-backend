import json
import frappe
from frappe import _
from .telemetry import (
    MIN_SAFE_SOC_PERCENT,
    is_vehicle_wake_suspended,
    get_cached_telemetry,
    _get_cache_key,
)

# Commands that transmit wake-up signals over the air to vehicle ECUs
WAKE_REQUIRING_COMMANDS = {
    "start_climate",
    "stop_climate",
    "set_climate",
    "lock_doors",
    "unlock_doors",
    "open_trunk",
    "start_charge",
    "stop_charge",
}

# Expandable remote commands added in Phase 6
WAKE_REQUIRING_COMMANDS.update({
    "open_tailgate",
    "close_tailgate",
    "vent_windows",
    "close_windows",
    "prep_rspa_mode",
})

@frappe.whitelist()
def execute_command(vin: str, command: str, parameters=None) -> dict:
    """
    Executes or queues a vehicle command.
    Ensures any wake-up or remote action is suspended if traction battery SOC < 20%
    to protect the 12V auxiliary battery from deep discharge.
    """
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except Exception:
            parameters = {}
    parameters = parameters or {}

    # Read current cached state to avoid unnecessary vehicle wake-up
    cached_state = get_cached_telemetry(vin)
    current_soc = float(cached_state.get("battery", {}).get("state_of_charge", 0.0))
    is_plugged_in = bool(cached_state.get("battery", {}).get("is_plugged_in", False))

    # 12V Battery Protection Enforcement
    if command in WAKE_REQUIRING_COMMANDS and is_vehicle_wake_suspended(current_soc):
        # Exception: Allow start_charge only if plugged in, as charging restores HV and 12V batteries
        if command == "start_charge" and is_plugged_in:
            frappe.logger("kia_ev6").info(
                f"Allowing start_charge for {vin} despite SOC {current_soc}% because vehicle is plugged in."
            )
        else:
            msg = (
                f"Vehicle wake-up suspended for command '{command}': "
                f"High-voltage battery SOC is {current_soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%). "
                "Remote wake-up suspended to prevent 12V auxiliary battery drain."
            )
            frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
            frappe.throw(_(msg), frappe.ValidationError)

    vehicle = frappe.get_doc("EV6 Vehicle", vin)

    # Process supported commands
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

    # Invalidate telemetry cache so next read reflects updated command state
    frappe.cache().delete_value(_get_cache_key(vin))

    return {
        "status": "queued",
        "command": command,
        "vin": vin,
        "wake_up_suspended": False,
        "parameters": parameters,
    }


@frappe.whitelist()
def set_climate(vin: str, enabled: bool, target_temperature: float = 21.5) -> dict:
    """Convenience endpoint to configure climate pre-conditioning."""
    cmd = "start_climate" if enabled else "stop_climate"
    return execute_command(
        vin=vin,
        command=cmd,
        parameters={"target_temperature": float(target_temperature)},
    )


@frappe.whitelist()
def open_tailgate(vin: str) -> dict:
    """Remotely open the tailgate after safety SOC check."""
    cached = get_cached_telemetry(vin)
    soc = float(cached.get("battery", {}).get("state_of_charge", 0.0))
    if is_vehicle_wake_suspended(soc):
        msg = (
            f"Tailgate open suspended: HV battery SOC is {soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%)."
        )
        frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
        frappe.throw(_(msg), frappe.ValidationError)

    return execute_command(vin=vin, command="open_tailgate")


@frappe.whitelist()
def close_tailgate(vin: str) -> dict:
    """Remotely close the tailgate after safety SOC check."""
    cached = get_cached_telemetry(vin)
    soc = float(cached.get("battery", {}).get("state_of_charge", 0.0))
    if is_vehicle_wake_suspended(soc):
        msg = (
            f"Tailgate close suspended: HV battery SOC is {soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%)."
        )
        frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
        frappe.throw(_(msg), frappe.ValidationError)

    return execute_command(vin=vin, command="close_tailgate")


@frappe.whitelist()
def vent_windows(vin: str) -> dict:
    """Vent (slightly open) the windows after safety SOC check."""
    cached = get_cached_telemetry(vin)
    soc = float(cached.get("battery", {}).get("state_of_charge", 0.0))
    if is_vehicle_wake_suspended(soc):
        msg = (
            f"Window vent suspended: HV battery SOC is {soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%)."
        )
        frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
        frappe.throw(_(msg), frappe.ValidationError)

    return execute_command(vin=vin, command="vent_windows")


@frappe.whitelist()
def close_windows(vin: str) -> dict:
    """Close windows (cancel vent) after safety SOC check."""
    cached = get_cached_telemetry(vin)
    soc = float(cached.get("battery", {}).get("state_of_charge", 0.0))
    if is_vehicle_wake_suspended(soc):
        msg = (
            f"Window close suspended: HV battery SOC is {soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%)."
        )
        frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
        frappe.throw(_(msg), frappe.ValidationError)

    return execute_command(vin=vin, command="close_windows")


@frappe.whitelist()
def prep_rspa_mode(vin: str) -> dict:
    """Prepare vehicle for RSPA Reverse operation after safety SOC check."""
    cached = get_cached_telemetry(vin)
    soc = float(cached.get("battery", {}).get("state_of_charge", 0.0))
    if is_vehicle_wake_suspended(soc):
        msg = (
            f"RSPA prep suspended: HV battery SOC is {soc:.1f}% (< {MIN_SAFE_SOC_PERCENT}%)."
        )
        frappe.logger("kia_ev6").warning(f"[{vin}] {msg}")
        frappe.throw(_(msg), frappe.ValidationError)

    return execute_command(vin=vin, command="prep_rspa_mode")


@frappe.whitelist()
def set_charging_limit(vin: str, target_soc_limit: int) -> dict:
    """Updates target state-of-charge charging limit without waking the vehicle."""
    limit = int(target_soc_limit)
    if limit < 50 or limit > 100:
        frappe.throw(_("Target SOC limit must be between 50% and 100%."))

    frappe.db.set_value("EV6 Vehicle", vin, "target_soc_limit", limit)
    frappe.cache().delete_value(_get_cache_key(vin))

    return {"status": "success", "target_soc_limit": limit}


@frappe.whitelist()
def update_vehicle_profile(vin: str, trim: str = None, drivetrain: str = None, model_year: int = None, vehicle_color: str = None) -> dict:
    """Updates vehicle trim, drivetrain, year, and color hex string."""
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
        "vehicle_name": vehicle.vehicle_name,
        "trim": vehicle.trim,
        "drivetrain": vehicle.drivetrain,
        "model_year": vehicle.model_year,
        "vehicle_color": vehicle.vehicle_color,
    }


def evaluate_hourly_automations():
    """
    Hourly scheduler task to evaluate active EV6 Automation Rules.
    Safely suspends rule execution if vehicle HV SOC < 20% to prevent 12V battery drain.
    """
    logger = frappe.logger("kia_ev6")
    rules = frappe.get_all(
        "EV6 Automation Rule",
        filters={"is_enabled": 1},
        fields=["name", "title", "vehicle", "trigger_type", "action_type", "parameters"],
    )

    for rule in rules:
        vin = rule.vehicle
        if not vin:
            continue

        cached_state = get_cached_telemetry(vin)
        soc = float(cached_state.get("battery", {}).get("state_of_charge", 0.0))

        # Check 12V Battery Protection
        if is_vehicle_wake_suspended(soc):
            logger.warning(
                f"[Automation] Rule '{rule.title}' for {vin} suspended: "
                f"SOC is {soc}% (< {MIN_SAFE_SOC_PERCENT}%). 12V protection active."
            )
            continue

        # Evaluate and trigger action if conditions met
        try:
            logger.info(f"[Automation] Evaluating rule '{rule.title}' for vehicle {vin}")
            # Action execution hook
        except Exception as e:
            logger.error(f"[Automation] Error evaluating rule '{rule.title}': {str(e)}")
