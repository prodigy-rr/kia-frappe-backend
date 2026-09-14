import frappe

@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    """Authenticate and create user session for mobile client."""
    login_manager = frappe.auth.LoginManager()
    login_manager.authenticate(user=usr, pwd=pwd)
    login_manager.post_login()
    user = frappe.get_doc("User", frappe.session.user)
    return {
        "status": "success",
        "user": user.name,
        "full_name": user.full_name,
        "sid": frappe.session.sid,
    }

@frappe.whitelist()
def get_current_user():
    """Returns currently authenticated user details."""
    user = frappe.get_doc("User", frappe.session.user)
    return {
        "user": user.name,
        "full_name": user.full_name,
        "email": user.email,
    }
