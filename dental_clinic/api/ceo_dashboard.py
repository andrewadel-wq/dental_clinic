import frappe
from frappe import _


CEO_ROLES = ("CEO", "System Manager")


def _check_ceo_access():
    """Verify the current user has CEO dashboard access."""
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in CEO_ROLES):
        frappe.throw(
            _("You do not have permission to access the CEO Dashboard. Required role: CEO or System Manager."),
            frappe.PermissionError
        )


@frappe.whitelist()
def get_procurement_details(po_name):
    """
    Get detailed procurement information for a Purchase Order (CEO view).
    Shows per-item breakdown: requesting nurse, doctor, room, price analysis, buffer.

    Called by the "Check Procurement Details" button on PO form.
    """
    _check_ceo_access()

    po = frappe.get_doc("Purchase Order", po_name)
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
            "buffer_analysis": {},
        }

        # Get requesting nurses/doctors/rooms from source MRs
        if bm_name:
            mr_items = frappe.db.sql("""
                SELECT
                    mri.item_code, mri.qty, mri.uom,
                    mr.name as mr_name, mr.owner as requested_by,
                    mr.custom_doctor_name as doctor,
                    mr.custom_room as room,
                    mr.custom_branch as branch,
                    mr.transaction_date as request_date
                FROM `tabMaterial Request Item` mri
                JOIN `tabMaterial Request` mr ON mri.parent = mr.name
                JOIN `tabBranch Master MR` bmmr ON bmmr.material_request = mr.name
                JOIN `tabBranch Master` bm ON bmmr.parent = bm.name
                WHERE bm.name = %s AND mri.item_code = %s
            """, (bm_name, po_item.item_code), as_dict=True)

            for mr_item in mr_items:
                full_name = frappe.db.get_value("User", mr_item.requested_by, "full_name") or mr_item.requested_by
                item_detail["requestors"].append({
                    "nurse": full_name,
                    "nurse_email": mr_item.requested_by,
                    "doctor": mr_item.doctor or "General Use",
                    "room": mr_item.room or "",
                    "qty": mr_item.qty,
                    "branch": mr_item.branch or "",
                    "request_date": str(mr_item.request_date) if mr_item.request_date else "",
                })

        # Get price history (last 5 purchases)
        price_history = frappe.db.sql("""
            SELECT
                poi.rate, poi.qty, poi.uom,
                po2.name as po_name, po2.supplier, po2.supplier_name,
                po2.transaction_date as date
            FROM `tabPurchase Order Item` poi
            JOIN `tabPurchase Order` po2 ON poi.parent = po2.name
            WHERE poi.item_code = %s
                AND po2.docstatus = 1
                AND po2.name != %s
            ORDER BY po2.transaction_date DESC
            LIMIT 5
        """, (po_item.item_code, po_name), as_dict=True)

        item_detail["price_history"] = price_history

        # Price analysis
        if price_history:
            rates = [h.rate for h in price_history if h.rate]
            if rates:
                avg_rate = sum(rates) / len(rates)
                min_rate = min(rates)
                max_rate = max(rates)
                current_rate = po_item.rate or 0

                if avg_rate > 0:
                    variance_pct = ((current_rate - avg_rate) / avg_rate) * 100
                else:
                    variance_pct = 0

                item_detail["price_analysis"] = {
                    "current_rate": current_rate,
                    "avg_historical_rate": round(avg_rate, 2),
                    "min_rate": min_rate,
                    "max_rate": max_rate,
                    "variance_pct": round(variance_pct, 1),
                    "status": "Higher" if variance_pct > 10 else ("Lower" if variance_pct < -10 else "Normal"),
                }

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
                    status = "+%d Buffer" % int(difference)
                else:
                    status = "%d Under" % int(difference)

                item_detail["buffer_analysis"] = {
                    "total_requested": bm_item.total_requested_qty or 0,
                    "available_stock": bm_item.available_qty or 0,
                    "net_required": net_required,
                    "to_buy": to_buy,
                    "difference": difference,
                    "status": status,
                }

        details.append(item_detail)

    # Summary
    total_amount = sum(d["amount"] or 0 for d in details)
    items_with_buffer = sum(1 for d in details if d.get("buffer_analysis", {}).get("difference", 0) > 0)
    items_price_higher = sum(1 for d in details if d.get("price_analysis", {}).get("status") == "Higher")

    return {
        "details": details,
        "summary": {
            "total_items": len(details),
            "total_amount": total_amount,
            "items_with_buffer": items_with_buffer,
            "items_price_higher": items_price_higher,
            "supplier": po.supplier_name or po.supplier,
            "branch_master": bm_name,
        }
    }


@frappe.whitelist()
def get_item_price_history(item_code, limit=10):
    """Get purchase price history for a specific item."""
    _check_ceo_access()

    history = frappe.db.sql("""
        SELECT
            poi.rate, poi.qty, poi.uom,
            po.name as po_name, po.supplier, po.supplier_name,
            po.transaction_date as date, po.grand_total as po_total
        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po ON poi.parent = po.name
        WHERE poi.item_code = %s
            AND po.docstatus = 1
        ORDER BY po.transaction_date DESC
        LIMIT %s
    """, (item_code, int(limit)), as_dict=True)

    # Calculate statistics
    rates = [h.rate for h in history if h.rate]
    stats = {}
    if rates:
        stats = {
            "avg_rate": round(sum(rates) / len(rates), 2),
            "min_rate": min(rates),
            "max_rate": max(rates),
            "latest_rate": rates[0] if rates else 0,
            "total_purchases": len(history),
        }

    return {
        "history": history,
        "stats": stats,
    }


@frappe.whitelist()
def get_ceo_summary():
    """
    Get CEO overview dashboard data.
    Shows: pending approvals, recent POs, spend by branch, etc.
    """
    _check_ceo_access()

    # Pending PO approvals
    pending_pos = frappe.get_all(
        "Purchase Order",
        filters={
            "workflow_state": "Awaiting CEO Approval",
            "docstatus": 0,
        },
        fields=["name", "supplier_name", "grand_total", "transaction_date", "custom_branch_master"],
        order_by="transaction_date desc"
    )

    # Recent approved POs (last 30 days)
    from frappe.utils import add_days, today
    recent_pos = frappe.db.sql("""
        SELECT
            name, supplier_name, grand_total, transaction_date,
            workflow_state, custom_branch_master
        FROM `tabPurchase Order`
        WHERE docstatus = 1
        AND transaction_date >= %s
        ORDER BY transaction_date DESC
        LIMIT 20
    """, add_days(today(), -30), as_dict=True)

    # Spend by branch (last 30 days)
    spend_by_branch = frappe.db.sql("""
        SELECT
            bm.branch,
            COUNT(DISTINCT po.name) as po_count,
            SUM(po.grand_total) as total_spend
        FROM `tabPurchase Order` po
        LEFT JOIN `tabBranch Master` bm ON po.custom_branch_master = bm.name
        WHERE po.docstatus = 1
        AND po.transaction_date >= %s
        GROUP BY bm.branch
    """, add_days(today(), -30), as_dict=True)

    return {
        "pending_approvals": pending_pos,
        "pending_count": len(pending_pos),
        "recent_pos": recent_pos,
        "spend_by_branch": spend_by_branch,
    }
