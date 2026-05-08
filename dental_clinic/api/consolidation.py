import frappe
from frappe import _
from dental_clinic.utils.consolidation import (
    get_approved_mrs_for_branch,
    consolidate_items_from_mrs,
    get_available_stock,
    get_main_warehouse_stock,
    get_branch_warehouse,
    refresh_stock_levels,
)


CONSOLIDATION_ROLES = ("Store Keeper", "Procurement Manager", "Nurse In Charge", "Head Nurse", "System Manager")


def _check_consolidation_access():
    """Verify the current user has consolidation access."""
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in CONSOLIDATION_ROLES):
        frappe.throw(
            _("You do not have permission to access Consolidation functions."),
            frappe.PermissionError
        )


@frappe.whitelist()
def consolidate_branch_mrs(branch, posting_date=None):
    """
    Consolidate all approved Material Requests for a branch into a Branch Master.

    Logic:
    1. Get all MRs where custom_branch = branch AND workflow_state = 'Approved'
       AND NOT already linked to a Branch Master
    2. Check if active BM exists for this branch
    3. If active BM exists: append new MRs to it
    4. If no active BM: create new Branch Master
    5. Group items by item_code, summing quantities
    6. Refresh stock levels
    """
    _check_consolidation_access()

    if not branch:
        frappe.throw(_("Branch is required"))

    if not posting_date:
        posting_date = frappe.utils.today()

    # Get approved MRs not yet consolidated
    new_mrs = get_approved_mrs_for_branch(branch, exclude_consolidated=True)

    if not new_mrs:
        frappe.throw(_("No new approved Material Requests found for branch {0}").format(branch))

    mr_names = [mr.name for mr in new_mrs]

    # Check if an active Branch Master exists for this branch
    active_bm_name = frappe.db.get_value(
        "Branch Master",
        {
            "branch": branch,
            "docstatus": 0,
            "status": ["in", ["Draft", "Pending Review"]]
        },
        "name"
    )

    if active_bm_name:
        # Append to existing BM
        bm = frappe.get_doc("Branch Master", active_bm_name)
        _append_mrs_to_bm(bm, new_mrs, mr_names)
        bm.save(ignore_permissions=True)
        action = "updated"
    else:
        # Create new Branch Master
        bm = _create_new_branch_master(branch, posting_date, new_mrs, mr_names)
        action = "created"

    # Refresh stock levels
    refresh_stock_levels(bm)
    bm.save(ignore_permissions=True)

    return {
        "branch_master": bm.name,
        "action": action,
        "items_count": len(bm.items),
        "mr_count": len(mr_names),
    }


def _append_mrs_to_bm(bm, new_mrs, mr_names):
    """Append new MRs and their items to an existing Branch Master."""
    # Add source MRs
    for mr in new_mrs:
        bm.append("source_material_requests", {
            "material_request": mr.name,
            "requested_by": mr.owner,
            "request_date": mr.transaction_date,
            "room": mr.custom_room or "",
            "doctor": mr.custom_doctor_name or mr.custom_doctor or "",
        })

    # Consolidate new items
    new_item_map = consolidate_items_from_mrs(mr_names)

    # Merge with existing items
    existing_items = {row.item_code: row for row in bm.items}

    for item_code, item_data in new_item_map.items():
        if item_code in existing_items:
            # Add to existing quantity
            row = existing_items[item_code]
            row.total_requested_qty = (row.total_requested_qty or 0) + item_data["total_requested_qty"]
            row.net_to_buy = max(0, row.total_requested_qty - (row.available_qty or 0))
        else:
            # Add new item row
            bm.append("items", {
                "item_code": item_data["item_code"],
                "item_name": item_data["item_name"],
                "total_requested_qty": item_data["total_requested_qty"],
                "available_qty": 0,
                "net_to_buy": item_data["total_requested_qty"],
                "approved_qty": 0,
                "uom": item_data["uom"],
                "rate": 0,
                "amount": 0,
                "warehouse": item_data["warehouse"],
            })

    # Add comment about new additions
    bm.add_comment("Info", _("Auto-appended {0} new Material Request(s): {1}").format(
        len(mr_names), ", ".join(mr_names)
    ))


def _create_new_branch_master(branch, posting_date, new_mrs, mr_names):
    """Create a new Branch Master from scratch."""
    bm = frappe.new_doc("Branch Master")
    bm.branch = branch
    bm.posting_date = posting_date
    bm.status = "Draft"

    # Add source MRs
    for mr in new_mrs:
        bm.append("source_material_requests", {
            "material_request": mr.name,
            "requested_by": mr.owner,
            "request_date": mr.transaction_date,
            "room": mr.custom_room or "",
            "doctor": mr.custom_doctor_name or mr.custom_doctor or "",
        })

    # Consolidate items
    item_map = consolidate_items_from_mrs(mr_names)

    for item_data in item_map.values():
        bm.append("items", {
            "item_code": item_data["item_code"],
            "item_name": item_data["item_name"],
            "total_requested_qty": item_data["total_requested_qty"],
            "available_qty": 0,
            "net_to_buy": item_data["total_requested_qty"],
            "approved_qty": 0,
            "uom": item_data["uom"],
            "rate": 0,
            "amount": 0,
            "warehouse": item_data["warehouse"],
        })

    bm.insert(ignore_permissions=True)
    return bm


@frappe.whitelist()
def refresh_branch_master_stock(branch_master):
    """
    Refresh stock levels for a Branch Master.
    Called by the "Refresh Stock Levels" button.
    """
    _check_consolidation_access()

    bm = frappe.get_doc("Branch Master", branch_master)
    refresh_stock_levels(bm)
    bm.save(ignore_permissions=True)

    return {
        "branch_master": bm.name,
        "items_count": len(bm.items),
        "message": _("Stock levels refreshed successfully"),
    }


@frappe.whitelist()
def reconsolidate_branch_master(branch_master):
    """
    Re-consolidate a Branch Master from scratch.
    Fetches ALL approved MRs for the branch and rebuilds the items table.
    """
    _check_consolidation_access()

    bm = frappe.get_doc("Branch Master", branch_master)

    if bm.docstatus != 0:
        frappe.throw(_("Cannot re-consolidate a submitted Branch Master"))

    branch = bm.branch

    # Get ALL approved MRs for this branch (including already-linked ones to THIS BM)
    all_mrs = frappe.get_all(
        "Material Request",
        filters={
            "custom_branch": branch,
            "workflow_state": "Approved",
            "docstatus": 1,
        },
        fields=["name", "owner", "transaction_date", "custom_room", "custom_doctor_name", "custom_doctor"]
    )

    # Also include MRs that are linked to OTHER BMs for this branch (shouldn't happen due to constraint)
    # But exclude MRs linked to OTHER branches' BMs
    other_bm_mrs = frappe.db.sql("""
        SELECT bmmr.material_request
        FROM `tabBranch Master MR` bmmr
        JOIN `tabBranch Master` bm ON bmmr.parent = bm.name
        WHERE bm.name != %s AND bm.branch != %s AND bm.docstatus != 2
    """, (branch_master, branch), as_dict=True)
    other_mr_names = {r.material_request for r in other_bm_mrs}

    # Filter out MRs belonging to other branches' BMs
    valid_mrs = [mr for mr in all_mrs if mr.name not in other_mr_names]

    if not valid_mrs:
        frappe.throw(_("No approved Material Requests found for branch {0}").format(branch))

    mr_names = [mr.name for mr in valid_mrs]

    # Clear and rebuild
    bm.items = []
    bm.source_material_requests = []

    # Add source MRs
    for mr in valid_mrs:
        bm.append("source_material_requests", {
            "material_request": mr.name,
            "requested_by": mr.owner,
            "request_date": mr.transaction_date,
            "room": mr.custom_room or "",
            "doctor": mr.custom_doctor_name or mr.custom_doctor or "",
        })

    # Consolidate items
    item_map = consolidate_items_from_mrs(mr_names)

    for item_data in item_map.values():
        bm.append("items", {
            "item_code": item_data["item_code"],
            "item_name": item_data["item_name"],
            "total_requested_qty": item_data["total_requested_qty"],
            "available_qty": 0,
            "net_to_buy": item_data["total_requested_qty"],
            "approved_qty": 0,
            "uom": item_data["uom"],
            "rate": 0,
            "amount": 0,
            "warehouse": item_data["warehouse"],
        })

    # Refresh stock levels
    refresh_stock_levels(bm)
    bm.save(ignore_permissions=True)

    return {
        "branch_master": bm.name,
        "items_count": len(bm.items),
        "mr_count": len(mr_names),
        "message": _("Re-consolidated {0} Material Requests with {1} items").format(
            len(mr_names), len(bm.items)
        ),
    }


@frappe.whitelist()
def get_consolidation_status():
    """
    Get consolidation status for all branches.
    Shows which branches have pending MRs that haven't been consolidated.
    """
    _check_consolidation_access()

    branches = frappe.get_all("Branch", fields=["name"])
    status = []

    for branch in branches:
        pending_mrs = get_approved_mrs_for_branch(branch.name, exclude_consolidated=True)
        active_bm = frappe.db.get_value(
            "Branch Master",
            {"branch": branch.name, "docstatus": 0, "status": ["in", ["Draft", "Pending Review"]]},
            ["name", "status"],
            as_dict=True
        )

        status.append({
            "branch": branch.name,
            "pending_mr_count": len(pending_mrs),
            "active_bm": active_bm.name if active_bm else None,
            "active_bm_status": active_bm.status if active_bm else None,
            "needs_consolidation": len(pending_mrs) > 0,
        })

    return status
