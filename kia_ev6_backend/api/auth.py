import frappe
from frappe import _

@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    """Authenticates user and returns persistent API keys for mobile storage."""
    login_manager = frappe.auth.LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()

    user = frappe.session.user
    user_doc = frappe.get_doc("User", user)

    # Auto-generate API keys for secure mobile storage if missing
    api_secret = user_doc.get_password("api_secret")
    if not user_doc.api_key or not api_secret:
        api_secret = frappe.generate_keys(user)
        frappe.db.commit()
        user_doc.reload()

    return {
        "status": "success",
        "user": user,
        "full_name": user_doc.full_name,
        "api_key": user_doc.api_key,
        "api_secret": api_secret,
    }

@frappe.whitelist()
def get_user_vehicles():
    """Returns all EV6 Vehicle records assigned to the logged-in user."""
    user = frappe.session.user

    # Assumes your EV6 Vehicle Doctype has an 'owner' Link field to the User Doctype
    vehicles = frappe.get_all(
        "EV6 Vehicle",
        filters={"owner": user},
        fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"]
    )

    # Fallback to system-wide search if user is a System Manager (for testing)
    if not vehicles and "System Manager" in frappe.get_roles(user):
        vehicles = frappe.get_all(
            "EV6 Vehicle",
            fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"]
        )

    return vehiclesimport frappe
from frappe import _

@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    """Authenticates user and returns persistent API keys for mobile storage."""
    login_manager = frappe.auth.LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()

    user = frappe.session.user
    user_doc = frappe.get_doc("User", user)

    # Auto-generate API keys for secure mobile storage if missing
    api_secret = user_doc.get_password("api_secret")
    if not user_doc.api_key or not api_secret:
        api_secret = frappe.generate_keys(user)
        frappe.db.commit()
        user_doc.reload()

    return {
        "status": "success",
        "user": user,
        "full_name": user_doc.full_name,
        "api_key": user_doc.api_key,
        "api_secret": api_secret,
    }

@frappe.whitelist()
def get_user_vehicles():
    """Returns all EV6 Vehicle records assigned to the logged-in user."""
    user = frappe.session.user

    # Assumes your EV6 Vehicle Doctype has an 'owner' Link field to the User Doctype
    vehicles = frappe.get_all(
        "EV6 Vehicle",
        filters={"owner": user},
        fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"]
    )

    # Fallback to system-wide search if user is a System Manager (for testing)
    if not vehicles and "System Manager" in frappe.get_roles(user):
        vehicles = frappe.get_all(
            "EV6 Vehicle",
            fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"]
        )

    return vehicles
