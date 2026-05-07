import frappe
from frappe import _


@frappe.whitelist()
def get_room_stock(room_warehouse, search=None):
    """
    Get current stock in a room warehouse.
    Shows items available for consumption/usage.
    """
    if not room_warehouse:
        frappe.throw(_("Room warehouse is required"))

    conditions = "b.warehouse = %s AND b.actual_qty > 0"
    params = [room_warehouse]

    if search:
        conditions += " AND (b.item_code LIKE %s OR i.item_name LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    items = frappe.db.sql("""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            b.actual_qty as available_qty,
            i.stock_uom as uom,
            b.warehouse
        FROM `tabBin` b
        JOIN `tabItem` i ON b.item_code = i.name
        WHERE {conditions}
        ORDER BY i.item_name
    """.format(conditions=conditions), params, as_dict=True)

    return items


@frappe.whitelist()
def get_rooms_for_branch(branch):
    """
    Get all room warehouses for a branch.
    Room warehouses contain 'Rm' in their name.
    """
    if not branch:
        frappe.throw(_("Branch is required"))

    # Map branch code to warehouse group
    branch_warehouse_map = {
        "SS": "SpringsSouk - DNA",
        "Mir": "UptownMirdif - DNA",
        "Mar": "MarinaWalk - DNA",
        "Jum": "Jum3 - DNA",
    }

    parent_wh = branch_warehouse_map.get(branch)
    if not parent_wh:
        # Try direct match
        parent_wh = frappe.db.get_value("Warehouse", {"name": ["like", f"%{branch}%"], "is_group": 1}, "name")

    if not parent_wh:
        return []

    rooms = frappe.get_all(
        "Warehouse",
        filters={
            "parent_warehouse": parent_wh,
            "is_group": 0,
            "name": ["like", "%Rm%"]
        },
        fields=["name", "warehouse_name"],
        order_by="name"
    )

    return rooms


@frappe.whitelist()
def record_usage(room_warehouse, items, px_file_number, doctor=None, notes=None):
    """
    Record material usage (consumption) from a room.
    Creates a Stock Entry (Material Issue) with mandatory PX File Number.

    Args:
        room_warehouse: Source room warehouse
        items: JSON list of [{item_code, qty}]
        px_file_number: Mandatory PX File number (patient file)
        doctor: Doctor name (Link to Doctor doctype)
        notes: Optional notes
    """
    import json

    if isinstance(items, str):
        items = json.loads(items)

    if not px_file_number:
        frappe.throw(_("PX File Number is mandatory for recording material usage"))

    if not items:
        frappe.throw(_("At least one item is required"))

    if not room_warehouse:
        frappe.throw(_("Room warehouse is required"))

    # Validate stock availability for all items before creating SE
    for item_data in items:
        item_code = item_data.get("item_code")
        qty = int(float(item_data.get("qty", 0)))

        if qty <= 0:
            frappe.throw(_("Quantity must be a positive number for item {0}").format(item_code))

        available = frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": room_warehouse},
            "actual_qty"
        ) or 0

        if available < qty:
            frappe.throw(
                _("Insufficient stock for {0}. Available: {1}, Requested: {2} in {3}").format(
                    item_code, int(available), qty, room_warehouse
                )
            )

    # Create Stock Entry (Material Issue = consumption)
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    se.company = "Drs. Nicolas & Asp"

    # Custom fields for tracking
    se.custom_px_file_number = px_file_number
    if doctor:
        se.custom_doctor = doctor
    if notes:
        se.custom_usage_notes = notes

    for item_data in items:
        qty = int(float(item_data.get("qty", 0)))
        if qty <= 0:
            continue

        se.append("items", {
            "item_code": item_data["item_code"],
            "qty": qty,
            "s_warehouse": room_warehouse,
        })

    se.insert(ignore_permissions=True)
    se.submit()

    return {
        "stock_entry": se.name,
        "px_file_number": px_file_number,
        "doctor": doctor,
        "items_count": len(se.items),
        "message": _("Usage recorded successfully. Stock Entry: {0}").format(se.name)
    }


@frappe.whitelist()
def get_usage_history(room_warehouse=None, doctor=None, px_file_number=None, from_date=None, to_date=None, limit=50):
    """
    Get material usage history.
    Filters by room, doctor, PX file, or date range.
    """
    conditions = "se.stock_entry_type = 'Material Issue' AND se.docstatus = 1"
    params = []

    if room_warehouse:
        conditions += " AND sei.s_warehouse = %s"
        params.append(room_warehouse)

    if doctor:
        conditions += " AND se.custom_doctor = %s"
        params.append(doctor)

    if px_file_number:
        conditions += " AND se.custom_px_file_number LIKE %s"
        params.append(f"%{px_file_number}%")

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
            se.custom_px_file_number as px_file_number,
            se.custom_doctor as doctor,
            se.custom_usage_notes as notes,
            sei.item_code,
            sei.item_name,
            sei.qty,
            sei.s_warehouse as room
        FROM `tabStock Entry Detail` sei
        JOIN `tabStock Entry` se ON sei.parent = se.name
        WHERE {conditions}
        ORDER BY se.posting_date DESC, se.creation DESC
        LIMIT %s
    """.format(conditions=conditions), params, as_dict=True)

    return history


@frappe.whitelist()
def get_frequently_used_items(room_warehouse, limit=20):
    """
    Get frequently used items in a room (for quick-add functionality).
    Based on historical Material Issue entries.
    """
    items = frappe.db.sql("""
        SELECT
            sei.item_code,
            i.item_name,
            i.stock_uom as uom,
            COUNT(*) as usage_count,
            SUM(sei.qty) as total_used,
            MAX(se.posting_date) as last_used
        FROM `tabStock Entry Detail` sei
        JOIN `tabStock Entry` se ON sei.parent = se.name
        JOIN `tabItem` i ON sei.item_code = i.name
        WHERE se.stock_entry_type = 'Material Issue'
        AND se.docstatus = 1
        AND sei.s_warehouse = %s
        GROUP BY sei.item_code
        ORDER BY usage_count DESC
        LIMIT %s
    """, (room_warehouse, int(limit)), as_dict=True)

    return items
