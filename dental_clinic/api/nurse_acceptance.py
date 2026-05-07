import frappe
from frappe import _


@frappe.whitelist()
def get_pending_acceptances(branch=None, room=None):
    """
    Get items pending nurse acceptance.
    These are Stock Entries (Material Transfer) where target is a Transit warehouse,
    meaning items have been dispatched but not yet accepted by the nurse.

    The flow is:
    1. NIC dispatches item from Main → Transit (via Items Dashboard)
    2. Item appears here as "pending acceptance"
    3. Nurse clicks "Accept" → system creates another SE from Transit → Room
    """
    conditions = """
        se.stock_entry_type = 'Material Transfer'
        AND se.docstatus = 1
        AND sei.t_warehouse LIKE '%%Transit%%'
        AND se.custom_accepted = 0
    """
    params = []

    if branch:
        # Filter by branch's transit warehouse
        branch_warehouse_map = {
            "SS": "SS-Transit",
            "Mir": "Mir-Transit",
            "Mar": "Mar-Transit",
            "Jum": "Jum-Transit",
        }
        transit_pattern = branch_warehouse_map.get(branch, f"{branch}%Transit")
        conditions += " AND sei.t_warehouse LIKE %s"
        params.append(f"%{transit_pattern}%")

    if room:
        # Filter by intended target room (stored in custom field)
        conditions += " AND se.custom_target_room = %s"
        params.append(room)

    pending = frappe.db.sql("""
        SELECT
            se.name as stock_entry,
            se.posting_date,
            se.posting_time,
            se.custom_target_room as target_room,
            se.custom_doctor as doctor,
            se.custom_source_mr as source_mr,
            sei.item_code,
            sei.item_name,
            sei.qty,
            sei.s_warehouse as source_warehouse,
            sei.t_warehouse as transit_warehouse,
            se.owner as dispatched_by
        FROM `tabStock Entry Detail` sei
        JOIN `tabStock Entry` se ON sei.parent = se.name
        WHERE {conditions}
        ORDER BY se.posting_date DESC, se.posting_time DESC
    """.format(conditions=conditions), params, as_dict=True)

    # Add dispatched_by name
    for item in pending:
        item["dispatched_by_name"] = frappe.db.get_value("User", item.dispatched_by, "full_name") or item.dispatched_by

    return pending


@frappe.whitelist()
def accept_items(stock_entries, target_room=None):
    """
    Accept dispatched items - moves them from Transit to the target Room.
    Creates a new Stock Entry (Material Transfer) from Transit → Room.

    Args:
        stock_entries: JSON list of stock entry names to accept
        target_room: Override target room (if not specified, uses custom_target_room from original SE)
    """
    import json

    if isinstance(stock_entries, str):
        stock_entries = json.loads(stock_entries)

    if not stock_entries:
        frappe.throw(_("Please select at least one item to accept"))

    results = []
    errors = []

    for se_name in stock_entries:
        try:
            result = _accept_single_entry(se_name, target_room)
            results.append(result)
        except Exception as e:
            errors.append({"stock_entry": se_name, "error": str(e)})

    return {
        "accepted": results,
        "errors": errors,
        "message": _("{0} item(s) accepted successfully").format(len(results)) if results else _("No items accepted"),
    }


def _accept_single_entry(se_name, override_target_room=None):
    """Accept a single stock entry - move from transit to room."""
    original_se = frappe.get_doc("Stock Entry", se_name)

    if original_se.custom_accepted:
        frappe.throw(_("Stock Entry {0} has already been accepted").format(se_name))

    # Determine target room
    target_room = override_target_room or original_se.custom_target_room

    if not target_room:
        frappe.throw(
            _("No target room specified for Stock Entry {0}. Please specify a room.").format(se_name)
        )

    # Create acceptance Stock Entry (Transit → Room)
    acceptance_se = frappe.new_doc("Stock Entry")
    acceptance_se.stock_entry_type = "Material Transfer"
    acceptance_se.company = "Drs. Nicolas & Asp"
    acceptance_se.custom_acceptance_of = se_name
    acceptance_se.custom_doctor = original_se.custom_doctor

    for item in original_se.items:
        # Validate transit warehouse has stock
        transit_stock = frappe.db.get_value(
            "Bin",
            {"item_code": item.item_code, "warehouse": item.t_warehouse},
            "actual_qty"
        ) or 0

        if transit_stock < item.qty:
            frappe.throw(
                _("Insufficient stock in transit for {0}. Available: {1}, Required: {2}").format(
                    item.item_code, int(transit_stock), int(item.qty)
                )
            )

        acceptance_se.append("items", {
            "item_code": item.item_code,
            "qty": item.qty,
            "s_warehouse": item.t_warehouse,  # From transit
            "t_warehouse": target_room,  # To room
        })

    acceptance_se.insert(ignore_permissions=True)
    acceptance_se.submit()

    # Mark original SE as accepted
    original_se.db_set("custom_accepted", 1)
    original_se.db_set("custom_accepted_by", frappe.session.user)
    original_se.db_set("custom_acceptance_date", frappe.utils.today())
    original_se.db_set("custom_acceptance_se", acceptance_se.name)

    return {
        "original_se": se_name,
        "acceptance_se": acceptance_se.name,
        "target_room": target_room,
    }


@frappe.whitelist()
def reject_items(stock_entries, reason=None):
    """
    Reject dispatched items - moves them back from Transit to source warehouse.
    Creates a reverse Stock Entry (Material Transfer) from Transit → Source.

    Args:
        stock_entries: JSON list of stock entry names to reject
        reason: Reason for rejection
    """
    import json

    if isinstance(stock_entries, str):
        stock_entries = json.loads(stock_entries)

    if not stock_entries:
        frappe.throw(_("Please select at least one item to reject"))

    results = []
    errors = []

    for se_name in stock_entries:
        try:
            result = _reject_single_entry(se_name, reason)
            results.append(result)
        except Exception as e:
            errors.append({"stock_entry": se_name, "error": str(e)})

    return {
        "rejected": results,
        "errors": errors,
        "message": _("{0} item(s) rejected and returned to source").format(len(results)) if results else _("No items rejected"),
    }


def _reject_single_entry(se_name, reason=None):
    """Reject a single stock entry - move from transit back to source."""
    original_se = frappe.get_doc("Stock Entry", se_name)

    if original_se.custom_accepted:
        frappe.throw(_("Stock Entry {0} has already been accepted and cannot be rejected").format(se_name))

    # Create return Stock Entry (Transit → Source)
    return_se = frappe.new_doc("Stock Entry")
    return_se.stock_entry_type = "Material Transfer"
    return_se.company = "Drs. Nicolas & Asp"
    return_se.custom_rejection_of = se_name
    if reason:
        return_se.custom_rejection_reason = reason

    for item in original_se.items:
        return_se.append("items", {
            "item_code": item.item_code,
            "qty": item.qty,
            "s_warehouse": item.t_warehouse,  # From transit
            "t_warehouse": item.s_warehouse,  # Back to source
        })

    return_se.insert(ignore_permissions=True)
    return_se.submit()

    # Mark original SE as rejected
    original_se.db_set("custom_accepted", 2)  # 2 = rejected
    original_se.db_set("custom_rejection_reason", reason or "")
    original_se.db_set("custom_rejection_se", return_se.name)

    # Add comment
    original_se.add_comment("Info", _("Rejected by {0}. Reason: {1}").format(
        frappe.session.user, reason or "Not specified"
    ))

    return {
        "original_se": se_name,
        "return_se": return_se.name,
        "reason": reason,
    }


@frappe.whitelist()
def get_acceptance_history(branch=None, from_date=None, to_date=None, limit=50):
    """Get history of accepted/rejected items."""
    conditions = """
        se.stock_entry_type = 'Material Transfer'
        AND se.docstatus = 1
        AND sei.t_warehouse LIKE '%%Transit%%'
        AND se.custom_accepted != 0
    """
    params = []

    if branch:
        branch_warehouse_map = {
            "SS": "SS-Transit",
            "Mir": "Mir-Transit",
            "Mar": "Mar-Transit",
            "Jum": "Jum-Transit",
        }
        transit_pattern = branch_warehouse_map.get(branch, f"{branch}%Transit")
        conditions += " AND sei.t_warehouse LIKE %s"
        params.append(f"%{transit_pattern}%")

    if from_date:
        conditions += " AND se.posting_date >= %s"
        params.append(from_date)

    if to_date:
        conditions += " AND se.posting_date <= %s"
        params.append(to_date)

    params.append(int(limit))

    history = frappe.db.sql("""
        SELECT
            se.name as stock_entry,
            se.posting_date,
            se.custom_target_room as target_room,
            se.custom_doctor as doctor,
            se.custom_accepted as status,
            se.custom_accepted_by as accepted_by,
            se.custom_acceptance_date as acceptance_date,
            sei.item_code,
            sei.item_name,
            sei.qty
        FROM `tabStock Entry Detail` sei
        JOIN `tabStock Entry` se ON sei.parent = se.name
        WHERE {conditions}
        ORDER BY se.posting_date DESC
        LIMIT %s
    """.format(conditions=conditions), params, as_dict=True)

    # Map status codes
    for item in history:
        item["status_label"] = "Accepted" if item.status == 1 else "Rejected"
        if item.accepted_by:
            item["accepted_by_name"] = frappe.db.get_value("User", item.accepted_by, "full_name") or item.accepted_by

    return history
