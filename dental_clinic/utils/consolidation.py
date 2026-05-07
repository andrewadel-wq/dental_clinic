import frappe
from frappe import _


def get_available_stock(item_code, warehouse=None):
    """
    Get current stock balance for an item.
    If warehouse is specified, get stock for that warehouse.
    If not, get total stock across all warehouses.
    """
    if warehouse:
        bin_data = frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "actual_qty"
        )
        return bin_data or 0
    else:
        total = frappe.db.sql("""
            SELECT COALESCE(SUM(actual_qty), 0) as total
            FROM `tabBin`
            WHERE item_code = %s
        """, item_code)[0][0]
        return total or 0


def get_main_warehouse_stock(item_code):
    """Get stock in the main/central warehouse (Jum- Main Store - DNA)."""
    # Query for the main warehouse - using pattern matching to be resilient
    main_warehouses = frappe.db.sql("""
        SELECT name FROM `tabWarehouse`
        WHERE name LIKE '%%Main Store%%' AND is_group = 0
        LIMIT 1
    """, as_dict=True)

    if main_warehouses:
        return get_available_stock(item_code, main_warehouses[0].name)
    return 0


def get_branch_warehouse(branch):
    """
    Get the main warehouse for a branch.
    Maps branch code to warehouse name.
    """
    # Try direct lookup: branch warehouses follow pattern like "SS-Main - DNA"
    branch_map = {
        "SS": "SpringsSouk - DNA",
        "Mir": "UptownMirdif - DNA",
        "Mar": "MarinaWalk - DNA",
        "Jum": "Jum3 - DNA",
    }

    warehouse_group = branch_map.get(branch)
    if warehouse_group:
        # Find the Main sub-warehouse under this group
        main_wh = frappe.db.get_value(
            "Warehouse",
            {"parent_warehouse": warehouse_group, "name": ["like", "%Main%"]},
            "name"
        )
        if main_wh:
            return main_wh

    # Fallback: try to find warehouse matching branch name
    wh = frappe.db.get_value(
        "Warehouse",
        {"name": ["like", f"%{branch}%Main%"], "is_group": 0},
        "name"
    )
    return wh


def get_approved_mrs_for_branch(branch, exclude_consolidated=True):
    """
    Get all approved Material Requests for a branch that haven't been consolidated yet.
    """
    filters = {
        "custom_branch": branch,
        "workflow_state": "Approved",
        "docstatus": 1,
    }

    mrs = frappe.get_all(
        "Material Request",
        filters=filters,
        fields=["name", "owner", "transaction_date", "custom_room", "custom_doctor_name", "custom_doctor"]
    )

    if exclude_consolidated:
        # Exclude MRs already linked to a Branch Master
        existing_mr_links = frappe.get_all(
            "Branch Master MR",
            fields=["material_request"]
        )
        existing_mr_names = {r.material_request for r in existing_mr_links}
        mrs = [mr for mr in mrs if mr.name not in existing_mr_names]

    return mrs


def consolidate_items_from_mrs(mr_names):
    """
    Given a list of MR names, consolidate their items by item_code.
    Returns a dict of item_code -> consolidated item data.
    """
    if not mr_names:
        return {}

    items = frappe.db.sql("""
        SELECT
            mri.item_code, mri.item_name, mri.qty, mri.uom, mri.warehouse,
            mr.name as mr_name, mr.custom_room as room
        FROM `tabMaterial Request Item` mri
        JOIN `tabMaterial Request` mr ON mri.parent = mr.name
        WHERE mr.name IN ({})
    """.format(", ".join(["%s"] * len(mr_names))), mr_names, as_dict=True)

    # Consolidate by item_code
    item_map = {}
    for item in items:
        key = item.item_code
        if key not in item_map:
            item_map[key] = {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "total_requested_qty": 0,
                "uom": item.uom or "Nos",
                "warehouse": item.warehouse or "",
            }
        item_map[key]["total_requested_qty"] += item.qty

    return item_map


def refresh_stock_levels(bm_doc):
    """
    Refresh available stock levels for all items in a Branch Master.
    Queries the Bin doctype for actual_qty per item per warehouse.
    """
    for item in bm_doc.items:
        # Get stock in the branch's main warehouse
        branch_wh = get_branch_warehouse(bm_doc.branch)
        available = 0

        if branch_wh:
            available = get_available_stock(item.item_code, branch_wh)

        # Also check main store
        main_stock = get_main_warehouse_stock(item.item_code)

        item.available_qty = available + main_stock
        item.net_to_buy = max(0, (item.total_requested_qty or 0) - item.available_qty - (item.inter_branch_fulfilled or 0))

    return bm_doc
