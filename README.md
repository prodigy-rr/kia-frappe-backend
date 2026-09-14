# Kia EV6 Backend (ERPNext / Frappe App)

Custom Frappe app providing:
- Vehicle state persistence and telemetry logging (`EV6 Vehicle`, `EV6 Telemetry Log`)
- Dynamic automation rule configuration (`EV6 Automation Rule`)
- Whitelisted REST API endpoints for Flutter mobile & desktop client communication
- Scheduled background jobs for vehicle telemetry polling and charging automation

## Installation into Bench

```bash
bench get-app /path/to/kia_ev6_backend
bench --site [site-name] install-app kia_ev6_backend
bench --site [site-name] migrate
```
