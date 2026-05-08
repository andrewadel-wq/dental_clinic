import frappe
from frappe import _


DASHBOARD_ROLES = ("Store Keeper", "Nurse In Charge", "Head Nurse", "System Manager")


def _check_dashboard_access():
    """Verify the current user has Items Dashboard access."""
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in DASHBOARD_ROLES):
        frappe.throw(
            _("You do not have permission to access the Items Dashboard."),
            frappe.PermissionError
        )


def _get_user_allowed_branches():
    """
    Get the branches the current user is allowed to access.
    Returns a list of branch codes, or None if user is admin (all access).
    """
    user = frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return None  # All access

    # Get user's warehouse permissions
    permissions = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Warehouse"},
        fields=["for_value"]
    )

    if not permissions:
        # Also check Branch-level user permissions
        branch_perms = frappe.get_all(
            "User Permission",
            filters={"user": user, "allow": "Branch"},
            fields=["for_value"]
        )
        if branch_perms:
            return [p.for_value for p in branch_perms]
        return []

    # Map warehouses to branches
    branches = []
    for perm in permissions:
        branch = _warehouse_to_branch(perm.for_value)
        if branch and branch not in branches:
            branches.append(branch)

    return branches


def _enforce_branch_filter(branch, allowed_branches):
    """
    Enforce branch isolation. If user specifies a branch, validate it.
    If user doesn't specify, restrict to their allowed branches.
    Returns the branch filter value or raises an error.
    """
    if allowed_branches is None:
        # Admin - no restriction
        return branch

    if branch:
        # User specified a branch - validate they have access
        if branch not in allowed_branches:
            frappe.throw(
                _("You do not have permission to access branch {0}").format(branch),
                frappe.PermissionError
            )
        return branch

    # No branch specified - return None but we'll filter in the query
    return None


@frappe.whitelist()
def get_items_view(branch=None, search=None):
    """
    Get aggregated items from active Material Requests.
    Shows: Item Code, Item Name, Total Requested Qty, Moved Qty, Remaining Qty, MR Count.

    Filters by branch (for NIC role) or shows all (for Store Keeper/Head Nurse).
    Enforces server-side branch isolation based on user permissions.
    """
    _check_dashboard_access()

    allowed_branches = _get_user_allowed_branches()
    branch = _enforce_branch_filter(branch, allowed_branches)

    conditions = """
        mr.workflow_state IN ('Approved', 'Pending Head Nurse Review', 'Pending NIC Review', 'Pending Procurement')
        AND mr.docstatus IN (0, 1)
        AND (mri.qty - COALESCE(mri.custom_moved_quantity, 0)) > 0
    """

    params = []

    if branch:
        conditions += " AND mr.custom_branch = %s"
        params.append(branch)
    elif allowed_branches is not None and allowed_branches:
        # Non-admin without specific branch filter - restrict to their branches
        placeholders = ", ".join(["%s"] * len(allowed_branches))
        conditions += f" AND mr.custom_branch IN ({placeholders})"
        params.extend(allowed_branches)
    elif allowed_branches is not None and not allowed_branches:
        # User has no branch access - return empty
        return []

    if search:
        conditions += " AND (mri.item_code LIKE %s OR mri.item_name LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    items = frappe.db.sql("""
        SELECT
            mri.item_code,
            mri.item_name,
            mri.stock_uom,
            SUM(mri.qty) as total_requested_qty,
            SUM(COALESCE(mri.custom_moved_quantity, 0)) as total_moved_qty,
            SUM(mri.qty - COALESCE(mri.custom_moved_quantity, 0)) as remaining_qty,
            COUNT(DISTINCT mr.name) as mr_count,
            mr.custom_branch as branch
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mri.parent = mr.name
        WHERE {conditions}
        GROUP BY mri.item_code, mr.custom_branch
        ORDER BY remaining_qty DESC, mri.item_code
    """.format(conditions=conditions), params, as_dict=True)

    # Add available stock for each item
    for item in items:
        item["available_stock"] = _get_total_available_stock(item.item_code)
        item["available_in_branch"] = _get_branch_stock(item.item_code, item.branch)

    return items


@frappe.whitelist()
def get_rooms_view(branch=None):
    """
    Get rooms view - grouped by target warehouse/room.
    Shows: Room Name, MR Count, Items Count, Branch.
    Enforces server-side branch isolation.
    """
    _check_dashboard_access()

    allowed_branches = _get_user_allowed_branches()
    branch = _enforce_branch_filter(branch, allowed_branches)

    conditions = """
        mr.workflow_state IN ('Approved', 'Pending Head Nurse Review', 'Pending NIC Review', 'Pending Procurement')
        AND mr.docstatus IN (0, 1)
    """

    params = []

    if branch:
        conditions += " AND mr.custom_branch = %s"
        params.append(branch)
    elif allowed_branches is not None and allowed_branches:
        placeholders = ", ".join(["%s"] * len(allowed_branches))
        conditions += f" AND mr.custom_branch IN ({placeholders})"
        params.extend(allowed_branches)
    elif allowed_branches is not None and not allowed_branches:
        return []

    rooms = frappe.db.sql("""
        SELECT
            mr.custom_room as room,
            mr.custom_branch as branch,
            COUNT(DISTINCT mr.name) as mr_count,
            COUNT(DISTINCT mri.item_code) as item_count,
            SUM(mri.qty) as total_qty
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mri.parent = mr.name
        WHERE {conditions}
        AND mr.custom_room IS NOT NULL AND mr.custom_room != ''
        GROUP BY mr.custom_room, mr.custom_branch
        ORDER BY mr.custom_branch, mr.custom_room
    """.format(conditions=conditions), params, as_dict=True)

    return rooms


@frappe.whitelist()
def get_item_detail(item_code, branch=None):
    """
    Get detailed information for a specific item.
    Shows: Available stock per warehouse, all MRs requesting this item.
    """
    _check_dashboard_access()

    allowed_branches = _get_user_allowed_branches()
    branch = _enforce_branch_filter(branch, allowed_branches)

    # Get stock in all warehouses
    stock_by_warehouse = frappe.db.sql("""
        SELECT
            warehouse, actual_qty, reserved_qty,
            (actual_qty - reserved_qty) as available_qty
        FROM `tabBin`
        WHERE item_code = %s AND actual_qty > 0
        ORDER BY actual_qty DESC
    """, item_code, as_dict=True)

    # Get all MRs requesting this item (with remaining qty > 0)
    conditions = """
        mri.item_code = %s
        AND mr.workflow_state IN ('Approved', 'Pending Head Nurse Review', 'Pending NIC Review', 'Pending Procurement')
        AND mr.docstatus IN (0, 1)
        AND (mri.qty - COALESCE(mri.custom_moved_quantity, 0)) > 0
    """
    params = [item_code]

    if branch:
        conditions += " AND mr.custom_branch = %s"
        params.append(branch)
    elif allowed_branches is not None and allowed_branches:
        placeholders = ", ".join(["%s"] * len(allowed_branches))
        conditions += f" AND mr.custom_branch IN ({placeholders})"
        params.extend(allowed_branches)

    requesting_mrs = frappe.db.sql("""
        SELECT
            mr.name as mr_name,
            mr.owner as requested_by,
            mr.custom_doctor_name as doctor,
            mr.custom_room as room,
            mr.custom_branch as branch,
            mri.qty as requested_qty,
            COALESCE(mri.custom_moved_quantity, 0) as moved_qty,
            (mri.qty - COALESCE(mri.custom_moved_quantity, 0)) as remaining_qty,
            mri.name as mr_item_name,
            mri.uom
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mri.parent = mr.name
        WHERE {conditions}
        ORDER BY mr.transaction_date DESC
    """.format(conditions=conditions), params, as_dict=True)

    # Get full names for requestors
    for mr in requesting_mrs:
        mr["requested_by_name"] = frappe.db.get_value("User", mr.requested_by, "full_name") or mr.requested_by

    # Get item details
    item_info = frappe.db.get_value(
        "Item", item_code,
        ["item_name", "item_group", "stock_uom", "description"],
        as_dict=True
    )

    return {
        "item_info": item_info,
        "stock_by_warehouse": stock_by_warehouse,
        "requesting_mrs": requesting_mrs,
    }


@frappe.whitelist()
def dispatch_item(item_code, source_warehouse, target_warehouse, qty, doctor=None, material_request=None, material_request_item=None):
    """
    Dispatch an item from source warehouse to target warehouse (room).
    Creates a Stock Entry (Material Transfer).

    Args:
        item_code: Item to dispatch
        source_warehouse: Source warehouse (where stock exists)
        target_warehouse: Target warehouse (room)
        qty: Quantity to dispatch
        doctor: Doctor this dispatch is for (optional)
        material_request: Source MR name (optional, for tracking)
        material_request_item: Source MR Item name (optional, for moved_qty update)
    """
    _check_dashboard_access()

    # Additional check: only Store Keeper and System Manager can dispatch
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in ("Store Keeper", "System Manager")):
        frappe.throw(
            _("Only Store Keepers can dispatch items from the dashboard."),
            frappe.PermissionError
        )

    qty = int(float(qty))
    if qty <= 0:
        frappe.throw(_("Quantity must be a positive whole number"))

    # Validate stock availability
    from dental_clinic.utils.consolidation import get_available_stock
    available = get_available_stock(item_code, source_warehouse)
    if available < qty:
        frappe.throw(
            _("Insufficient stock. Available: {0}, Requested: {1} in warehouse {2}").format(
                int(available), qty, source_warehouse
            )
        )

    # Determine if we should use transit warehouse (for Nurse Acceptance flow)
    use_transit = _should_use_transit(target_warehouse)

    if use_transit:
        transit_wh = _get_transit_warehouse(target_warehouse)
        if transit_wh:
            actual_target = transit_wh
        else:
            actual_target = target_warehouse
    else:
        actual_target = target_warehouse

    # Create Stock Entry - using user's own permissions
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.company = "Drs. Nicolas & Asp"

    # Store the intended final room for nurse acceptance
    if use_transit and actual_target != target_warehouse:
        se.custom_target_room = target_warehouse

    # Add custom fields for tracking
    if doctor:
        se.custom_doctor = doctor
    if material_request:
        se.custom_source_mr = material_request
    se.custom_dispatched_from_dashboard = 1

    se.append("items", {
        "item_code": item_code,
        "qty": qty,
        "s_warehouse": source_warehouse,
        "t_warehouse": actual_target,
        "material_request": material_request or None,
        "material_request_item": material_request_item or None,
    })

    # Use ignore_permissions only for Stock Entry creation since Store Keeper
    # may not have submit permission on Stock Entry but should be able to dispatch
    se.insert(ignore_permissions=True)
    se.submit()

    # Update MR Item moved quantity if MR item reference provided
    if material_request_item:
        _update_mr_item_moved_qty(material_request_item, qty)

    result = {
        "stock_entry": se.name,
        "item_code": item_code,
        "qty": qty,
        "source": source_warehouse,
        "target": actual_target,
        "uses_transit": use_transit,
    }

    if use_transit:
        result["pending_acceptance"] = True
        result["message"] = _("Item dispatched to transit. Nurse must accept to complete transfer to room.")
    else:
        result["message"] = _("Item dispatched successfully to {0}").format(target_warehouse)

    return result


def _should_use_transit(warehouse):
    """Check if the target warehouse is a room (should use transit flow)."""
    if not warehouse:
        return False
    # Room warehouses contain "Rm" or "Room" in their name
    wh_name = warehouse.lower()
    return "rm" in wh_name or "room" in wh_name


def _get_transit_warehouse(room_warehouse):
    """Get the transit warehouse for the branch that contains this room."""
    # Get parent warehouse group
    parent = frappe.db.get_value("Warehouse", room_warehouse, "parent_warehouse")
    if not parent:
        return None

    # Find transit warehouse under the same parent
    transit = frappe.db.get_value(
        "Warehouse",
        {"parent_warehouse": parent, "name": ["like", "%Transit%"]},
        "name"
    )
    return transit


def _update_mr_item_moved_qty(mr_item_name, qty):
    """Update the moved and remaining quantities on a Material Request Item."""
    mr_item = frappe.get_doc("Material Request Item", mr_item_name)
    current_moved = mr_item.custom_moved_quantity or 0
    new_moved = current_moved + qty

    frappe.db.set_value(
        "Material Request Item",
        mr_item_name,
        {
            "custom_moved_quantity": new_moved,
            "custom_remaining_quantity": max(0, mr_item.qty - new_moved)
        }
    )


def _get_total_available_stock(item_code):
    """Get total available stock across all warehouses."""
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0) as total
        FROM `tabBin`
        WHERE item_code = %s
    """, item_code)
    return result[0][0] if result else 0


def _get_branch_stock(item_code, branch):
    """Get available stock in a branch's warehouses."""
    if not branch:
        return 0

    from dental_clinic.utils.consolidation import get_branch_warehouse
    branch_wh = get_branch_warehouse(branch)
    if not branch_wh:
        return 0

    # Get stock in all child warehouses of the branch
    result = frappe.db.sql("""
        SELECT COALESCE(SUM(b.actual_qty), 0) as total
        FROM `tabBin` b
        JOIN `tabWarehouse` w ON b.warehouse = w.name
        WHERE b.item_code = %s
        AND (w.parent_warehouse = %s OR w.name = %s)
    """, (item_code, branch_wh, branch_wh))
    return result[0][0] if result else 0


@frappe.whitelist()
def get_user_branch():
    """
    Get the branch(es) assigned to the current user.
    Uses User Permission where allow = 'Warehouse'.
    """
    user = frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles(user):
        # Admin sees all branches
        return {"branches": frappe.get_all("Branch", fields=["name"]), "is_admin": True}

    # Get user's warehouse permissions
    permissions = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Warehouse"},
        fields=["for_value"]
    )

    if not permissions:
        return {"branches": [], "is_admin": False}

    # Map warehouses to branches
    branches = []
    for perm in permissions:
        # Find which branch this warehouse belongs to
        branch = _warehouse_to_branch(perm.for_value)
        if branch and branch not in branches:
            branches.append(branch)

    return {"branches": branches, "is_admin": False}


def _warehouse_to_branch(warehouse):
    """Map a warehouse name to a branch code."""
    warehouse_branch_map = {
        "SpringsSouk - DNA": "SS",
        "UptownMirdif - DNA": "Mir",
        "MarinaWalk - DNA": "Mar",
        "Jum3 - DNA": "Jum",
    }
    return warehouse_branch_map.get(warehouse)
