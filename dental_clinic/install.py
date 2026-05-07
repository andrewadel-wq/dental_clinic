"""
Post-install setup for Dental Clinic app.
Creates all required custom fields on standard doctypes.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Create custom fields required by the dental clinic app."""
    create_all_custom_fields()
    create_reports()
    frappe.db.commit()


DOCTOR_STOCK_LEDGER_SCRIPT = """
# Script Report: Doctor Stock Ledger
# Compatible with Frappe v16 RestrictedPython safe_exec
# - No import statements (frappe and _ are pre-injected)
# - No .format() on strings (use % formatting)
# - No augmented assignment on dict items (use simple assignment)
# - Filters accessible via `filters` variable
# - Output via: data = columns, result_data

conditions = "se.docstatus = 1 AND se.custom_doctor IS NOT NULL AND se.custom_doctor != ''"
params = []

if filters.get("doctor"):
    conditions = conditions + " AND se.custom_doctor = %s"
    params.append(filters["doctor"])

if filters.get("item_code"):
    conditions = conditions + " AND sei.item_code = %s"
    params.append(filters["item_code"])

if filters.get("from_date"):
    conditions = conditions + " AND se.posting_date >= %s"
    params.append(filters["from_date"])

if filters.get("to_date"):
    conditions = conditions + " AND se.posting_date <= %s"
    params.append(filters["to_date"])

if filters.get("branch"):
    branch = filters["branch"]
    conditions = conditions + " AND (sei.s_warehouse LIKE %s OR sei.t_warehouse LIKE %s)"
    params.append("%" + branch + "%")
    params.append("%" + branch + "%")

query = \"\"\"
    SELECT
        se.posting_date,
        se.custom_doctor as doctor,
        sei.item_code,
        sei.item_name,
        se.stock_entry_type,
        sei.qty,
        sei.s_warehouse,
        sei.t_warehouse,
        se.name as stock_entry,
        se.custom_px_file_number as px_file_number
    FROM `tabStock Entry Detail` sei
    JOIN `tabStock Entry` se ON sei.parent = se.name
    WHERE %s
    ORDER BY se.custom_doctor, sei.item_code, se.posting_date, se.posting_time
\"\"\" % conditions

entries = frappe.db.sql(query, params, as_dict=True)

result_data = []
balance_map = {}

for entry in entries:
    doctor = entry.get("doctor", "")
    item_code = entry.get("item_code", "")
    key = doctor + "||" + item_code

    if key not in balance_map:
        balance_map[key] = 0

    in_qty = 0
    out_qty = 0
    transaction_type = ""
    room = ""

    if entry.get("stock_entry_type") == "Material Transfer":
        in_qty = entry.get("qty", 0)
        transaction_type = "Received"
        room = entry.get("t_warehouse", "") or ""
    elif entry.get("stock_entry_type") == "Material Issue":
        out_qty = entry.get("qty", 0)
        transaction_type = "Used"
        room = entry.get("s_warehouse", "") or ""

    balance_map[key] = balance_map[key] + in_qty - out_qty

    result_data.append({
        "posting_date": entry.get("posting_date"),
        "doctor": doctor,
        "item_code": item_code,
        "item_name": entry.get("item_name", ""),
        "transaction_type": transaction_type,
        "in_qty": in_qty if in_qty > 0 else None,
        "out_qty": out_qty if out_qty > 0 else None,
        "balance": balance_map[key],
        "px_file_number": entry.get("px_file_number", ""),
        "room": room,
        "stock_entry": entry.get("stock_entry", ""),
    })

columns = [
    {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
    {"label": _("Doctor"), "fieldname": "doctor", "fieldtype": "Link", "options": "Doctor", "width": 150},
    {"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
    {"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
    {"label": _("Transaction Type"), "fieldname": "transaction_type", "fieldtype": "Data", "width": 130},
    {"label": _("In Qty"), "fieldname": "in_qty", "fieldtype": "Float", "width": 80},
    {"label": _("Out Qty"), "fieldname": "out_qty", "fieldtype": "Float", "width": 80},
    {"label": _("Balance"), "fieldname": "balance", "fieldtype": "Float", "width": 80},
    {"label": _("PX File"), "fieldname": "px_file_number", "fieldtype": "Data", "width": 120},
    {"label": _("Room"), "fieldname": "room", "fieldtype": "Data", "width": 120},
    {"label": _("Stock Entry"), "fieldname": "stock_entry", "fieldtype": "Link", "options": "Stock Entry", "width": 130},
]

data = columns, result_data
"""


def create_reports():
    """Create the Doctor Stock Ledger report.
    
    If a standard report exists, force-delete it via SQL and recreate as non-standard.
    This is needed because Frappe blocks editing/deleting standard reports via the ORM.
    """
    if frappe.db.exists("Report", "Doctor Stock Ledger"):
        # Check if it's a standard report (which can't be edited normally)
        is_std = frappe.db.get_value("Report", "Doctor Stock Ledger", "is_standard")
        if is_std == "Yes":
            # Force-delete via SQL to bypass the standard report protection
            frappe.db.sql("DELETE FROM `tabHas Role` WHERE parent='Doctor Stock Ledger' AND parenttype='Report'")
            frappe.db.sql("DELETE FROM `tabReport` WHERE name='Doctor Stock Ledger'")
            frappe.db.commit()
            print("Deleted standard Doctor Stock Ledger report (will recreate as non-standard)")
        else:
            # Non-standard report exists - just update it
            report = frappe.get_doc("Report", "Doctor Stock Ledger")
            report.report_type = "Script Report"
            report.module = "Stock"
            report.report_script = DOCTOR_STOCK_LEDGER_SCRIPT
            existing_roles = [r.role for r in report.roles]
            for role in ["System Manager", "Stock Manager", "Stock User", "Store Keeper", "Nurse In Charge", "Head Nurse", "CEO"]:
                if role not in existing_roles:
                    report.append("roles", {"role": role})
            report.save(ignore_permissions=True)
            print("Updated Doctor Stock Ledger report")
            return

    # Create fresh non-standard report
    report = frappe.new_doc("Report")
    report.report_name = "Doctor Stock Ledger"
    report.ref_doctype = "Stock Entry"
    report.report_type = "Script Report"
    report.is_standard = "No"
    report.module = "Stock"
    report.disabled = 0
    report.report_script = DOCTOR_STOCK_LEDGER_SCRIPT
    for role in ["System Manager", "Stock Manager", "Stock User", "Store Keeper", "Nurse In Charge", "Head Nurse", "CEO"]:
        report.append("roles", {"role": role})
    report.insert(ignore_permissions=True)
    print("Created Doctor Stock Ledger report (non-standard)")


def create_all_custom_fields():
    """Create all custom fields needed by the app on standard doctypes.
    
    Note: Fields that already exist on the site will be updated (not recreated).
    We must match the existing fieldtype exactly to avoid validation errors.
    """

    custom_fields = {
        # ─── Stock Entry Custom Fields ───
        "Stock Entry": [
            {
                "fieldname": "custom_target_room",
                "label": "Target Room",
                "fieldtype": "Link",
                "options": "Warehouse",
                "insert_after": "to_warehouse",
                "description": "Target room/warehouse for nurse acceptance",
            },
            {
                "fieldname": "custom_accepted",
                "label": "Acceptance Status",
                "fieldtype": "Int",
                "insert_after": "custom_target_room",
                "default": "0",
                "description": "0=Pending, 1=Accepted, 2=Rejected",
                "read_only": 1,
            },
            {
                "fieldname": "custom_accepted_by",
                "label": "Accepted By",
                "fieldtype": "Link",
                "options": "User",
                "insert_after": "custom_accepted",
                "read_only": 1,
            },
            {
                "fieldname": "custom_acceptance_date",
                "label": "Acceptance Date",
                "fieldtype": "Date",
                "insert_after": "custom_accepted_by",
                "read_only": 1,
            },
            {
                "fieldname": "custom_acceptance_se",
                "label": "Acceptance Stock Entry",
                "fieldtype": "Link",
                "options": "Stock Entry",
                "insert_after": "custom_acceptance_date",
                "read_only": 1,
            },
            {
                "fieldname": "custom_acceptance_of",
                "label": "Acceptance Of",
                "fieldtype": "Link",
                "options": "Stock Entry",
                "insert_after": "custom_acceptance_se",
                "read_only": 1,
                "description": "Original dispatch SE this acceptance is for",
            },
            {
                "fieldname": "custom_rejection_of",
                "label": "Rejection Of",
                "fieldtype": "Link",
                "options": "Stock Entry",
                "insert_after": "custom_acceptance_of",
                "read_only": 1,
            },
            {
                "fieldname": "custom_rejection_reason",
                "label": "Rejection Reason",
                "fieldtype": "Small Text",
                "insert_after": "custom_rejection_of",
                "read_only": 1,
            },
            {
                "fieldname": "custom_rejection_se",
                "label": "Rejection Stock Entry",
                "fieldtype": "Link",
                "options": "Stock Entry",
                "insert_after": "custom_rejection_reason",
                "read_only": 1,
            },
            {
                "fieldname": "custom_doctor",
                "label": "Doctor",
                "fieldtype": "Link",
                "options": "Doctor",
                "insert_after": "custom_rejection_se",
                "description": "Doctor associated with this stock movement",
            },
            {
                "fieldname": "custom_source_mr",
                "label": "Source Material Request",
                "fieldtype": "Link",
                "options": "Material Request",
                "insert_after": "custom_doctor",
                "description": "Material Request that triggered this dispatch",
            },
            {
                "fieldname": "custom_dispatched_from_dashboard",
                "label": "Dispatched from Dashboard",
                "fieldtype": "Check",
                "insert_after": "custom_source_mr",
                "default": "0",
                "read_only": 1,
            },
            {
                "fieldname": "custom_usage_notes",
                "label": "Usage Notes",
                "fieldtype": "Small Text",
                "insert_after": "custom_dispatched_from_dashboard",
                "description": "Notes about material usage",
            },
            {
                "fieldname": "custom_px_file_number",
                "label": "PX File Number",
                "fieldtype": "Data",
                "insert_after": "custom_usage_notes",
                "description": "Patient file number for material usage tracking",
            },
        ],

        # ─── Material Request Custom Fields ───
        # Note: custom_branch, custom_doctor, custom_doctor_name, custom_room
        # already exist on the site. We only add NEW fields that don't exist yet.
        # Existing fields are preserved as-is.
        "Material Request": [
            {
                "fieldname": "custom_branch",
                "label": "Branch",
                "fieldtype": "Link",
                "options": "Branch Master",
                "insert_after": "naming_series",
                "description": "Branch this request belongs to",
            },
            {
                "fieldname": "custom_doctor_name",
                "label": "Doctor Name",
                "fieldtype": "Link",
                "options": "Doctor",
                "insert_after": "custom_branch",
            },
            {
                "fieldname": "custom_room",
                "label": "Room",
                "fieldtype": "Link",
                "options": "Warehouse",
                "insert_after": "custom_doctor_name",
                "description": "Room/warehouse requesting materials",
            },
            {
                "fieldname": "custom_branch_master",
                "label": "Branch Master",
                "fieldtype": "Link",
                "options": "Branch Master",
                "insert_after": "custom_room",
                "read_only": 1,
                "description": "Branch Master this MR was consolidated into",
            },
            {
                "fieldname": "custom_consolidated",
                "label": "Consolidated",
                "fieldtype": "Check",
                "insert_after": "custom_branch_master",
                "default": "0",
                "read_only": 1,
            },
        ],

        # ─── Material Request Item Custom Fields ───
        "Material Request Item": [
            {
                "fieldname": "custom_moved_qty",
                "label": "Moved Qty",
                "fieldtype": "Float",
                "insert_after": "qty",
                "default": "0",
                "read_only": 1,
                "description": "Quantity already dispatched/moved",
            },
            {
                "fieldname": "custom_remaining_qty",
                "label": "Remaining Qty",
                "fieldtype": "Float",
                "insert_after": "custom_moved_qty",
                "read_only": 1,
                "description": "Quantity remaining to be dispatched",
            },
        ],

        # ─── Purchase Order Custom Fields ───
        "Purchase Order": [
            {
                "fieldname": "custom_auto_approved",
                "label": "Auto Approved",
                "fieldtype": "Check",
                "insert_after": "naming_series",
                "default": "0",
                "read_only": 1,
                "description": "Automatically approved (below AED 5,000 threshold)",
            },
            {
                "fieldname": "custom_source_branch_master",
                "label": "Source Branch Master",
                "fieldtype": "Link",
                "options": "Branch Master",
                "insert_after": "custom_auto_approved",
                "description": "Branch Master that generated this PO",
            },
            {
                "fieldname": "custom_procurement_notes",
                "label": "Procurement Notes",
                "fieldtype": "Small Text",
                "insert_after": "custom_source_branch_master",
            },
        ],
    }

    create_custom_fields(custom_fields, update=True)
    print("Dental Clinic: All custom fields created successfully")
