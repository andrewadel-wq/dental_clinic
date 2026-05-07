app_name = "dental_clinic"
app_title = "Dental Clinic"
app_publisher = "Apollonia Health"
app_description = "Custom dental clinic inventory management for Drs. Nicolas & Asp"
app_email = "itmg@nicolasasp.ae"
app_license = "MIT"
app_version = "0.0.1"

# Required apps
required_apps = ["frappe", "erpnext"]

# Installation hooks
after_install = "dental_clinic.install.after_install"
after_migrate = "dental_clinic.install.after_install"

# Document Events
# ----------------
doc_events = {
    "Material Request": {
        "on_update_after_submit": "dental_clinic.events.material_request.on_update_after_submit",
        "validate": "dental_clinic.events.material_request.validate",
    },
    "Purchase Order": {
        "before_submit": "dental_clinic.events.purchase_order.before_submit",
        "validate": "dental_clinic.events.purchase_order.validate",
    },
    "Stock Entry": {
        "on_submit": "dental_clinic.events.stock_entry.on_submit",
    },
    "Branch Master": {
        "validate": "dental_clinic.events.branch_master.validate",
        "before_submit": "dental_clinic.events.branch_master.before_submit",
    },
}

# Scheduled Tasks
# ----------------
# scheduler_events = {
#     "daily": [
#         "dental_clinic.tasks.daily_stock_check",
#     ],
# }

# Fixtures - export existing configuration
# ----------------
fixtures = [
    {
        "dt": "Workflow",
        "filters": [["name", "in", ["Material Request Approval", "Purchase Order - CEO Approval"]]]
    },
    {
        "dt": "Role",
        "filters": [["name", "in", ["Nurse", "Nurse In Charge", "Head Nurse", "Store Keeper", "CEO", "Procurement Manager"]]]
    },
]

# Override standard doctype classes (if needed)
# override_doctype_class = {
#     "Branch Master": "dental_clinic.overrides.branch_master.CustomBranchMaster",
# }

# Jinja template customizations
# jinja = {
#     "methods": [],
# }

# Website
# --------
# website_route_rules = []

# Include JS/CSS in desk
app_include_js = "/assets/dental_clinic/js/dental_clinic.bundle.js"
app_include_css = "/assets/dental_clinic/css/dental_clinic.bundle.css"
