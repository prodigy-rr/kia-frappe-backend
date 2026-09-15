import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    """
    Authenticates user credentials against Frappe.
    Generates and returns persistent API Key & Secret pair on successful login.
    """
    login_manager = frappe.auth.LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()

    user = frappe.session.user
    user_doc = frappe.get_doc("User", user)

    # Fetch or generate API Secret & Key dynamically
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
    """
    Returns all EV6 Vehicle documents assigned to the authenticated user.
    System Managers receive all vehicles registered in the system as a fallback.
    """
    user = frappe.session.user

    vehicles = frappe.get_all(
        "EV6 Vehicle",
        filters={"owner": user},
        fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"],
    )

    # Fallback for System Managers to view all vehicles
    if not vehicles and "System Manager" in frappe.get_roles(user):
        vehicles = frappe.get_all(
            "EV6 Vehicle",
            fields=["name", "vin", "vehicle_name", "trim", "drivetrain", "model_year", "vehicle_color"],
        )

    # Ensure VIN field falls back to document Name if unpopulated
    for v in vehicles:
        if not v.get("vin"):
            v["vin"] = v["name"]

    return vehicles
