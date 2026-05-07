import frappe
from frappe import _

# Auto-approval threshold in AED
PO_AUTO_APPROVAL_THRESHOLD = 5000


def validate(doc, method):
    """Validate Purchase Order before save."""
    # Validate integer quantities
    for item in doc.items:
        if item.qty and item.qty != int(item.qty):
            frappe.throw(
                _("Row {0}: Decimal quantities are not allowed. Please use whole numbers for item {1}.").format(
                    item.idx, item.item_code
                )
            )


def before_submit(doc, method):
    """
    Before submitting a Purchase Order:
    - If grand_total < threshold (AED 5,000): auto-approve (skip CEO approval)
    - If grand_total >= threshold: workflow handles it (goes to Awaiting CEO Approval)

    Note: This hook fires when the Store Keeper clicks "Submit for Approval" in the workflow.
    The workflow transition sets the state. This hook can override it for auto-approval.
    """
    if not doc.grand_total:
        return

    # Auto-approval logic for POs below threshold
    if doc.grand_total < PO_AUTO_APPROVAL_THRESHOLD:
        # Skip CEO approval - set directly to "Processing With Supplier"
        doc.workflow_state = "Processing With Supplier"
        frappe.msgprint(
            _("Purchase Order {0} auto-approved (total AED {1} is below the AED {2} threshold).").format(
                doc.name, doc.grand_total, PO_AUTO_APPROVAL_THRESHOLD
            ),
            alert=True,
            indicator="green"
        )


@frappe.whitelist()
def get_procurement_details(po_name):
    """
    Get procurement details for a Purchase Order (CEO view).
    Returns per-item breakdown showing: requesting nurse, doctor, room, price analysis.

    Called by the "Check Procurement Details" button on PO form.
    """
    po = frappe.get_doc("Purchase Order", po_name)

    # Get the Branch Master linked to this PO
    bm_name = po.custom_branch_master
    details = []

    for po_item in po.items:
        item_detail = {
            "item_code": po_item.item_code,
            "item_name": po_item.item_name,
            "qty": po_item.qty,
            "rate": po_item.rate,
            "amount": po_item.amount,
            "uom": po_item.uom,
            "requestors": [],
            "price_history": [],
            "buffer_analysis": {}
        }

        # Get requesting nurses/doctors/rooms from source MRs
        if bm_name:
            mr_items = frappe.db.sql("""
                SELECT
                    mri.item_code, mri.qty, mri.uom,
                    mr.name as mr_name, mr.owner as requested_by,
                    mr.custom_doctor_name as doctor,
                    mr.custom_room as room,
                    mr.custom_branch as branch
                FROM `tabMaterial Request Item` mri
                JOIN `tabMaterial Request` mr ON mri.parent = mr.name
                JOIN `tabBranch Master MR` bmmr ON bmmr.material_request = mr.name
                JOIN `tabBranch Master` bm ON bmmr.parent = bm.name
                WHERE bm.name = %s AND mri.item_code = %s
            """, (bm_name, po_item.item_code), as_dict=True)

            for mr_item in mr_items:
                # Get full name of requestor
                full_name = frappe.db.get_value("User", mr_item.requested_by, "full_name") or mr_item.requested_by
                item_detail["requestors"].append({
                    "nurse": full_name,
                    "nurse_email": mr_item.requested_by,
                    "doctor": mr_item.doctor or "General Use",
                    "room": mr_item.room or "",
                    "qty": mr_item.qty,
                    "branch": mr_item.branch or "",
                })

        # Get price history (last 5 purchases of this item)
        price_history = frappe.db.sql("""
            SELECT
                poi.rate, poi.qty, poi.uom,
                po.name as po_name, po.supplier,
                po.transaction_date as date
            FROM `tabPurchase Order Item` poi
            JOIN `tabPurchase Order` po ON poi.parent = po.name
            WHERE poi.item_code = %s
                AND po.docstatus = 1
                AND po.name != %s
            ORDER BY po.transaction_date DESC
            LIMIT 5
        """, (po_item.item_code, po_name), as_dict=True)

        item_detail["price_history"] = price_history

        # Buffer analysis
        if bm_name:
            bm_item = frappe.db.get_value(
                "Branch Master Item",
                {"parent": bm_name, "item_code": po_item.item_code},
                ["total_requested_qty", "available_qty", "net_to_buy", "approved_qty"],
                as_dict=True
            )
            if bm_item:
                net_required = bm_item.net_to_buy or 0
                to_buy = po_item.qty
                difference = to_buy - net_required

                if difference == 0:
                    status = "Exact Match"
                elif difference > 0:
                    status = "+{} Extra".format(int(difference))
                else:
                    status = "{} Less".format(int(difference))

                item_detail["buffer_analysis"] = {
                    "total_requested": bm_item.total_requested_qty or 0,
                    "available_stock": bm_item.available_qty or 0,
                    "net_required": net_required,
                    "to_buy": to_buy,
                    "difference": difference,
                    "status": status,
                }

        details.append(item_detail)

    return details


@frappe.whitelist()
def get_price_history(item_code, limit=10):
    """Get purchase price history for an item."""
    return frappe.db.sql("""
        SELECT
            poi.rate, poi.qty, poi.uom,
            po.name as po_name, po.supplier, po.supplier_name,
            po.transaction_date as date
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON poi.parent = po.name
        WHERE poi.item_code = %s
            AND po.docstatus = 1
        ORDER BY po.transaction_date DESC
        LIMIT %s
    """, (item_code, limit), as_dict=True)
