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


def create_reports():
    """Create the Doctor Stock Ledger report if it doesn't exist."""
    if not frappe.db.exists("Report", "Doctor Stock Ledger"):
        report = frappe.new_doc("Report")
        report.report_name = "Doctor Stock Ledger"
        report.ref_doctype = "Stock Entry"
        report.report_type = "Script Report"
        report.is_standard = "No"
        report.module = "Dental Clinic"
        report.disabled = 0
        report.insert(ignore_permissions=True)
        # Add roles
        for role in ["System Manager", "Nurse In Charge", "Head Nurse", "Store Keeper", "CEO"]:
            report.append("roles", {"role": role})
        report.save(ignore_permissions=True)
        print("✅ Dental Clinic: Doctor Stock Ledger report created")


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
    print("✅ Dental Clinic: All custom fields created successfully")
