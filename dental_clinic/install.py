"""
Post-install setup for Dental Clinic app.
Creates all required custom fields on standard doctypes,
missing warehouses, and reports.
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Create custom fields required by the dental clinic app."""
    create_all_custom_fields()
    create_missing_warehouses()
    create_reports()
    update_mr_workflow()
    frappe.db.commit()


# ─── Missing Warehouses ───────────────────────────────────────────────────────

def create_missing_warehouses():
    """Create transit and special warehouses that are missing from the new system."""
    company = "Drs. Nicolas & Asp"
    warehouses_to_create = [
        {
            "warehouse_name": "MarinaWalk-Transit",
            "parent_warehouse": "MarinaWalk - DNA",
            "is_group": 0,
            "company": company,
        },
        {
            "warehouse_name": "UpTown-Transit",
            "parent_warehouse": "UptownMirdif - DNA",
            "is_group": 0,
            "company": company,
        },
        {
            "warehouse_name": "Rejected Items",
            "parent_warehouse": "All Warehouses - DNA",
            "is_group": 0,
            "company": company,
        },
    ]

    for wh_data in warehouses_to_create:
        # Check if warehouse already exists (with or without company suffix)
        wh_name = wh_data["warehouse_name"] + " - DNA"
        if not frappe.db.exists("Warehouse", wh_name):
            # Also check without suffix
            if not frappe.db.exists("Warehouse", {"warehouse_name": wh_data["warehouse_name"]}):
                wh = frappe.new_doc("Warehouse")
                wh.warehouse_name = wh_data["warehouse_name"]
                wh.parent_warehouse = wh_data["parent_warehouse"]
                wh.is_group = wh_data["is_group"]
                wh.company = wh_data["company"]
                wh.insert(ignore_permissions=True)
                print(f"Created warehouse: {wh.name}")
            else:
                print(f"Warehouse {wh_data['warehouse_name']} already exists")
        else:
            print(f"Warehouse {wh_name} already exists")


# ─── Doctor Stock Ledger Report Script ────────────────────────────────────────

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


# ─── MR Workflow Update ────────────────────────────────────────────────────────

def update_mr_workflow():
    """
    Ensure the Material Request Approval workflow has the
    'Closed (Internally Fulfilled)' state.

    This state is used when items are dispatched from existing stock
    without going through the full procurement cycle.
    """
    workflow_name = "Material Request Approval"
    if not frappe.db.exists("Workflow", workflow_name):
        print(f"Workflow '{workflow_name}' not found - skipping workflow update")
        return

    wf = frappe.get_doc("Workflow", workflow_name)

    # Check if the state already exists
    existing_states = [s.state for s in wf.states]
    if "Closed (Internally Fulfilled)" in existing_states:
        print("Workflow state 'Closed (Internally Fulfilled)' already exists")
        return

    # Add the new state
    wf.append("states", {
        "state": "Closed (Internally Fulfilled)",
        "doc_status": "1",
        "update_field": "workflow_state",
        "update_value": "Closed (Internally Fulfilled)",
        "allow_edit": "Store Keeper",
    })

    # Add transitions TO this state from 'Approved'
    wf.append("transitions", {
        "state": "Approved",
        "action": "Close (Internally Fulfilled)",
        "next_state": "Closed (Internally Fulfilled)",
        "allowed": "Store Keeper",
        "allow_self_approval": 1,
    })

    # Also allow Head Nurse to close
    wf.append("transitions", {
        "state": "Approved",
        "action": "Close (Internally Fulfilled)",
        "next_state": "Closed (Internally Fulfilled)",
        "allowed": "Head Nurse",
        "allow_self_approval": 1,
    })

    wf.save(ignore_permissions=True)
    print("Added 'Closed (Internally Fulfilled)' state to Material Request Approval workflow")


# ─── Custom Fields ────────────────────────────────────────────────────────────

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
            {
                "fieldname": "custom_reject_reason",
                "label": "Reject Reason",
                "fieldtype": "Small Text",
                "insert_after": "custom_consolidated",
                "description": "Reason for rejecting this Material Request",
            },
        ],

        # ─── Material Request Item Custom Fields ───
        "Material Request Item": [
            {
                "fieldname": "custom_moved_quantity",
                "label": "Moved Qty",
                "fieldtype": "Float",
                "insert_after": "qty",
                "default": "0",
                "read_only": 1,
                "description": "Quantity already dispatched/moved",
            },
            {
                "fieldname": "custom_remaining_quantity",
                "label": "Remaining Qty",
                "fieldtype": "Float",
                "insert_after": "custom_moved_quantity",
                "read_only": 1,
                "description": "Quantity remaining to be dispatched",
            },
            {
                "fieldname": "custom_shade",
                "label": "Shade",
                "fieldtype": "Data",
                "insert_after": "custom_remaining_quantity",
                "description": "Shade information for dental items",
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
                "fieldname": "custom_branch_master",
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
                "insert_after": "custom_branch_master",
            },
            {
                "fieldname": "custom_ceo_return_reason",
                "label": "CEO Return Reason",
                "fieldtype": "Small Text",
                "insert_after": "custom_procurement_notes",
                "description": "Reason provided by CEO when sending back a PO for revision",
            },
        ],

        # ─── Item Custom Fields (from original system) ───
        "Item": [
            {
                "fieldname": "custom_shade",
                "label": "Shade",
                "fieldtype": "Data",
                "insert_after": "item_name",
                "description": "Shade information for dental items",
            },
            {
                "fieldname": "custom_expiry_date",
                "label": "Expiry Date",
                "fieldtype": "Date",
                "insert_after": "custom_shade",
                "description": "Expiry date for perishable dental materials",
            },
            {
                "fieldname": "custom_material_type",
                "label": "Material Type",
                "fieldtype": "Data",
                "insert_after": "custom_expiry_date",
                "description": "Material classification for dental items",
            },
            {
                "fieldname": "custom_deductible",
                "label": "Deductible",
                "fieldtype": "Check",
                "insert_after": "custom_material_type",
                "default": "0",
                "description": "Whether this item is deductible from doctor allocation",
            },
        ],
    }

    create_custom_fields(custom_fields, update=True)
    print("Dental Clinic: All custom fields created successfully")
