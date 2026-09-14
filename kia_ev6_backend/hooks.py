app_name = "kia_ev6_backend"
app_title = "Kia EV6 Backend"
app_publisher = "Kia Automation Team"
app_description = "Custom Frappe/ERPNext app for Kia EV6 vehicle telemetry, automation, and controls"
app_email = "admin@example.com"
app_license = "mit"

# Includes in <head>
# ------------------

# Scheduled Tasks
# ---------------
scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            "kia_ev6_backend.api.telemetry.poll_vehicles_telemetry"
        ],
        "0 * * * *": [
            "kia_ev6_backend.api.commands.evaluate_hourly_automations"
        ]
    }
}
