import frappe
from frappe import _


def execute(filters=None):
    """
    Doctor Stock Ledger Report
    Shows per-doctor stock movements with running balance.

    Tracks:
    - Items dispatched TO a doctor (via Material Transfer with custom_doctor)
    - Items consumed BY a doctor (via Material Issue with custom_doctor)
    - Running balance per doctor per item
    """
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "label": _("Date"),
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "label": _("Doctor"),
            "fieldname": "doctor",
            "fieldtype": "Link",
            "options": "Doctor",
            "width": 150,
        },
        {
            "label": _("Item Code"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 150,
        },
        {
            "label": _("Item Name"),
            "fieldname": "item_name",
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "label": _("Transaction Type"),
            "fieldname": "transaction_type",
            "fieldtype": "Data",
            "width": 130,
        },
        {
            "label": _("In Qty"),
            "fieldname": "in_qty",
            "fieldtype": "Float",
            "width": 80,
        },
        {
            "label": _("Out Qty"),
            "fieldname": "out_qty",
            "fieldtype": "Float",
            "width": 80,
        },
        {
            "label": _("Balance"),
            "fieldname": "balance",
            "fieldtype": "Float",
            "width": 80,
        },
        {
            "label": _("PX File"),
            "fieldname": "px_file_number",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Room"),
            "fieldname": "room",
            "fieldtype": "Data",
            "width": 120,
        },
        {
            "label": _("Stock Entry"),
            "fieldname": "stock_entry",
            "fieldtype": "Link",
            "options": "Stock Entry",
            "width": 130,
        },
    ]


def get_data(filters):
    conditions = "se.docstatus = 1 AND se.custom_doctor IS NOT NULL AND se.custom_doctor != ''"
    params = []

    if filters.get("doctor"):
        conditions += " AND se.custom_doctor = %s"
        params.append(filters["doctor"])

    if filters.get("item_code"):
        conditions += " AND sei.item_code = %s"
        params.append(filters["item_code"])

    if filters.get("from_date"):
        conditions += " AND se.posting_date >= %s"
        params.append(filters["from_date"])

    if filters.get("to_date"):
        conditions += " AND se.posting_date <= %s"
        params.append(filters["to_date"])

    if filters.get("branch"):
        conditions += " AND (sei.s_warehouse LIKE %s OR sei.t_warehouse LIKE %s)"
        branch = filters["branch"]
        params.extend([f"%{branch}%", f"%{branch}%"])

    # Get all stock movements linked to doctors
    entries = frappe.db.sql("""
        SELECT
            se.posting_date,
            se.custom_doctor as doctor,
            sei.item_code,
            sei.item_name,
            se.stock_entry_type,
            sei.qty,
            sei.s_warehouse,
            sei.t_warehouse,
            se.custom_px_file_number as px_file_number,
            se.name as stock_entry
        FROM `tabStock Entry Detail` sei
        JOIN `tabStock Entry` se ON sei.parent = se.name
        WHERE {conditions}
        ORDER BY se.custom_doctor, sei.item_code, se.posting_date, se.posting_time
    """.format(conditions=conditions), params, as_dict=True)

    # Calculate running balance per doctor per item
    data = []
    balance_tracker = {}  # (doctor, item_code) -> running balance

    for entry in entries:
        key = (entry.doctor, entry.item_code)
        if key not in balance_tracker:
            balance_tracker[key] = 0

        in_qty = 0
        out_qty = 0
        transaction_type = ""
        room = ""

        if entry.stock_entry_type == "Material Transfer":
            # Dispatch to doctor = IN
            in_qty = entry.qty
            transaction_type = "Received"
            room = entry.t_warehouse or ""
        elif entry.stock_entry_type == "Material Issue":
            # Consumption by doctor = OUT
            out_qty = entry.qty
            transaction_type = "Used"
            room = entry.s_warehouse or ""

        balance_tracker[key] += in_qty - out_qty

        data.append({
            "posting_date": entry.posting_date,
            "doctor": entry.doctor,
            "item_code": entry.item_code,
            "item_name": entry.item_name,
            "transaction_type": transaction_type,
            "in_qty": in_qty if in_qty > 0 else None,
            "out_qty": out_qty if out_qty > 0 else None,
            "balance": balance_tracker[key],
            "px_file_number": entry.px_file_number or "",
            "room": room,
            "stock_entry": entry.stock_entry,
        })

    return data
