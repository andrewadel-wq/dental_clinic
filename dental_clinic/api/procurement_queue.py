import frappe
from frappe import _


@frappe.whitelist()
def get_procurement_queue(branch=None, status=None, search=None):
    """
    Get the procurement queue - items from submitted Branch Masters that need POs.

    Shows items where net_to_buy > 0, grouped by Branch Master.
    Filters:
    - branch: filter by specific branch
    - status: filter by BM status (Approved, Ordered, etc.)
    - search: search by item code or name
    """
    conditions = "bm.docstatus = 1"
    params = []

    if branch:
        conditions += " AND bm.branch = %s"
        params.append(branch)

    if status:
        conditions += " AND bm.status = %s"
        params.append(status)
    else:
        # Default: show Approved BMs (ready for PO creation)
        conditions += " AND bm.status IN ('Approved', 'Partially Ordered')"

    if search:
        conditions += " AND (bmi.item_code LIKE %s OR bmi.item_name LIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    items = frappe.db.sql("""
        SELECT
            bm.name as branch_master,
            bm.branch,
            bm.status as bm_status,
            bm.posting_date,
            bmi.item_code,
            bmi.item_name,
            bmi.total_requested_qty,
            bmi.available_qty,
            bmi.net_to_buy,
            bmi.approved_qty,
            bmi.uom,
            bmi.rate,
            bmi.amount,
            bmi.name as bm_item_name
        FROM `tabBranch Master Item` bmi
        JOIN `tabBranch Master` bm ON bmi.parent = bm.name
        WHERE {conditions}
        AND bmi.net_to_buy > 0
        ORDER BY bm.branch, bmi.item_code
    """.format(conditions=conditions), params, as_dict=True)

    # Group by branch master for summary
    bm_summary = {}
    for item in items:
        bm_name = item.branch_master
        if bm_name not in bm_summary:
            bm_summary[bm_name] = {
                "branch_master": bm_name,
                "branch": item.branch,
                "status": item.bm_status,
                "posting_date": item.posting_date,
                "item_count": 0,
                "total_amount": 0,
            }
        bm_summary[bm_name]["item_count"] += 1
        bm_summary[bm_name]["total_amount"] += (item.amount or 0)

    return {
        "items": items,
        "summary": list(bm_summary.values()),
        "total_items": len(items),
    }


@frappe.whitelist()
def get_pending_po_items(branch_masters=None):
    """
    Get all items from selected Branch Masters that need to be included in a PO.
    Used by the "Export to PO" dialog.
    """
    if not branch_masters:
        frappe.throw(_("Please select at least one Branch Master"))

    if isinstance(branch_masters, str):
        import json
        branch_masters = json.loads(branch_masters)

    items = frappe.db.sql("""
        SELECT
            bmi.item_code,
            bmi.item_name,
            bmi.net_to_buy as qty,
            bmi.approved_qty,
            bmi.uom,
            bmi.rate,
            bm.name as branch_master,
            bm.branch
        FROM `tabBranch Master Item` bmi
        JOIN `tabBranch Master` bm ON bmi.parent = bm.name
        WHERE bm.name IN ({})
        AND bmi.net_to_buy > 0
        ORDER BY bmi.item_code
    """.format(", ".join(["%s"] * len(branch_masters))), branch_masters, as_dict=True)

    # Consolidate same items from different BMs
    consolidated = {}
    for item in items:
        key = item.item_code
        if key not in consolidated:
            consolidated[key] = {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": 0,
                "uom": item.uom,
                "rate": item.rate or 0,
                "source_branch_masters": [],
            }
        consolidated[key]["qty"] += (item.approved_qty or item.qty)
        if item.branch_master not in consolidated[key]["source_branch_masters"]:
            consolidated[key]["source_branch_masters"].append(item.branch_master)

    return list(consolidated.values())


@frappe.whitelist()
def create_purchase_order(supplier, schedule_date, items, branch_masters):
    """
    Create a Purchase Order from the Procurement Queue.

    Args:
        supplier: Supplier name
        schedule_date: Required by date
        items: JSON list of items [{item_code, qty, rate, uom}]
        branch_masters: JSON list of Branch Master names to link
    """
    import json

    if isinstance(items, str):
        items = json.loads(items)
    if isinstance(branch_masters, str):
        branch_masters = json.loads(branch_masters)

    if not items:
        frappe.throw(_("No items to create Purchase Order"))
    if not supplier:
        frappe.throw(_("Supplier is required"))

    # Create PO
    po = frappe.new_doc("Purchase Order")
    po.supplier = supplier
    po.schedule_date = schedule_date
    po.company = "Drs. Nicolas & Asp"

    # Link to first Branch Master (PO can only link to one via custom_branch_master)
    if branch_masters:
        po.custom_branch_master = branch_masters[0]

    for item_data in items:
        qty = int(float(item_data.get("qty", 0)))
        if qty <= 0:
            continue

        po.append("items", {
            "item_code": item_data["item_code"],
            "item_name": item_data.get("item_name", ""),
            "qty": qty,
            "rate": float(item_data.get("rate", 0)),
            "uom": item_data.get("uom", "Nos"),
            "schedule_date": schedule_date,
        })

    if not po.items:
        frappe.throw(_("No valid items to create Purchase Order (all quantities are zero)"))

    po.insert(ignore_permissions=True)

    # Update Branch Master statuses to "Partially Ordered" or "Ordered"
    for bm_name in branch_masters:
        _update_bm_status_after_po(bm_name, po.name)

    return {
        "purchase_order": po.name,
        "items_count": len(po.items),
        "message": _("Purchase Order {0} created successfully with {1} items").format(po.name, len(po.items))
    }


def _update_bm_status_after_po(bm_name, po_name):
    """Update Branch Master status after PO creation."""
    bm = frappe.get_doc("Branch Master", bm_name)

    # Check if all items with net_to_buy > 0 have been ordered
    all_ordered = True
    for item in bm.items:
        if (item.net_to_buy or 0) > 0 and not _item_fully_ordered(item.item_code, bm_name):
            all_ordered = False
            break

    if all_ordered:
        bm.db_set("status", "Ordered")
    else:
        bm.db_set("status", "Partially Ordered")

    # Add comment about PO creation
    bm.add_comment("Info", _("Purchase Order {0} created from this Branch Master").format(po_name))


def _item_fully_ordered(item_code, bm_name):
    """Check if an item has been fully ordered via POs linked to this BM."""
    ordered_qty = frappe.db.sql("""
        SELECT COALESCE(SUM(poi.qty), 0)
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON poi.parent = po.name
        WHERE po.custom_branch_master = %s
        AND poi.item_code = %s
        AND po.docstatus = 1
    """, (bm_name, item_code))[0][0]

    bm_item_qty = frappe.db.get_value(
        "Branch Master Item",
        {"parent": bm_name, "item_code": item_code},
        "net_to_buy"
    ) or 0

    return ordered_qty >= bm_item_qty


@frappe.whitelist()
def get_suppliers_for_items(item_codes):
    """
    Get suggested suppliers for a list of items.
    Returns suppliers who have previously supplied these items.
    """
    import json
    if isinstance(item_codes, str):
        item_codes = json.loads(item_codes)

    if not item_codes:
        return []

    suppliers = frappe.db.sql("""
        SELECT DISTINCT
            po.supplier, po.supplier_name,
            COUNT(DISTINCT poi.item_code) as items_supplied,
            MAX(po.transaction_date) as last_order_date
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON poi.parent = po.name
        WHERE poi.item_code IN ({})
        AND po.docstatus = 1
        GROUP BY po.supplier, po.supplier_name
        ORDER BY items_supplied DESC, last_order_date DESC
        LIMIT 10
    """.format(", ".join(["%s"] * len(item_codes))), item_codes, as_dict=True)

    # Also get default suppliers from Item doctype
    default_suppliers = frappe.db.sql("""
        SELECT DISTINCT
            isd.supplier,
            s.supplier_name
        FROM `tabItem Supplier` isd
        LEFT JOIN `tabSupplier` s ON isd.supplier = s.name
        WHERE isd.parent IN ({})
    """.format(", ".join(["%s"] * len(item_codes))), item_codes, as_dict=True)

    # Merge and deduplicate
    supplier_map = {}
    for s in suppliers:
        supplier_map[s.supplier] = s
    for s in default_suppliers:
        if s.supplier not in supplier_map:
            supplier_map[s.supplier] = {
                "supplier": s.supplier,
                "supplier_name": s.supplier_name or s.supplier,
                "items_supplied": 0,
                "last_order_date": None,
                "is_default": True,
            }

    return list(supplier_map.values())
