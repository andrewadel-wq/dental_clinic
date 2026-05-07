import frappe
from frappe import _


def validate(doc, method):
    """Validate Material Request before save."""
    # Ensure custom_doctor_name is used as the canonical doctor field
    if doc.custom_doctor_name and not doc.custom_doctor:
        doc.custom_doctor = doc.custom_doctor_name

    # Validate integer quantities on all items
    for item in doc.items:
        if item.qty and item.qty != int(item.qty):
            frappe.throw(
                _("Row {0}: Decimal quantities are not allowed. Please use whole numbers for item {1}.").format(
                    item.idx, item.item_code
                )
            )


def on_update_after_submit(doc, method):
    """
    Called when a Material Request is updated after submission.
    This fires when workflow_state changes (e.g., to 'Approved').

    Logic:
    - When MR reaches 'Approved' state, check if an active Branch Master exists for this branch
    - If yes: auto-append the MR items to the active Branch Master
    - If no: do nothing (consolidation will happen manually or via API)
    """
    if doc.workflow_state != "Approved":
        return

    branch = doc.custom_branch
    if not branch:
        return

    # Check if this MR is already linked to a Branch Master
    existing_link = frappe.db.exists(
        "Branch Master MR",
        {"material_request": doc.name}
    )
    if existing_link:
        return

    # Find active Branch Master for this branch (Draft or Pending Review, not yet Ordered)
    active_bm = get_active_branch_master(branch)
    if not active_bm:
        # No active BM exists - will be consolidated later via API/button
        return

    # Auto-append this MR to the active Branch Master
    append_mr_to_branch_master(doc, active_bm)


def get_active_branch_master(branch):
    """
    Find the active Branch Master for a given branch.
    Active means: docstatus=0 (Draft) and status in (Draft, Pending Review).
    Only ONE should exist per branch (enforced by branch_master.validate).
    """
    bm_name = frappe.db.get_value(
        "Branch Master",
        {
            "branch": branch,
            "docstatus": 0,
            "status": ["in", ["Draft", "Pending Review"]]
        },
        "name"
    )
    if bm_name:
        return frappe.get_doc("Branch Master", bm_name)
    return None


def append_mr_to_branch_master(mr_doc, bm_doc):
    """
    Append a Material Request's items to an existing Branch Master.
    - Adds items to the consolidated items table (sums if item already exists)
    - Adds the MR to the source_material_requests table
    - Flags the addition as "new" (for Head Nurse acceptance)
    """
    # Add MR to source table
    bm_doc.append("source_material_requests", {
        "material_request": mr_doc.name,
        "requested_by": mr_doc.owner,
        "request_date": mr_doc.transaction_date,
        "room": mr_doc.custom_room or "",
        "doctor": mr_doc.custom_doctor_name or mr_doc.custom_doctor or "",
    })

    # Consolidate items - add or sum quantities
    existing_items = {row.item_code: row for row in bm_doc.items}

    for mr_item in mr_doc.items:
        if mr_item.item_code in existing_items:
            # Item already exists in BM - add to total
            bm_row = existing_items[mr_item.item_code]
            bm_row.total_requested_qty = (bm_row.total_requested_qty or 0) + mr_item.qty
            # Recalculate net_to_buy
            bm_row.net_to_buy = max(0, bm_row.total_requested_qty - (bm_row.available_qty or 0))
        else:
            # New item - add row
            new_row = bm_doc.append("items", {
                "item_code": mr_item.item_code,
                "item_name": mr_item.item_name,
                "total_requested_qty": mr_item.qty,
                "available_qty": 0,
                "net_to_buy": mr_item.qty,
                "approved_qty": 0,
                "uom": mr_item.uom or "Nos",
                "rate": 0,
                "amount": 0,
                "warehouse": mr_item.warehouse or "",
            })
            existing_items[mr_item.item_code] = new_row

    # Mark that new additions were made (Head Nurse must accept)
    if not bm_doc.get("has_new_additions"):
        # Use a custom field or comment to flag new additions
        bm_doc.add_comment("Info", _("New Material Request {0} auto-appended. Head Nurse must review new additions.").format(mr_doc.name))

    bm_doc.flags.ignore_permissions = True
    bm_doc.save()

    frappe.msgprint(
        _("Material Request {0} has been auto-appended to active Branch Master {1}").format(
            mr_doc.name, bm_doc.name
        ),
        alert=True,
        indicator="green"
    )
