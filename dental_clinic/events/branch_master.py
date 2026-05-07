import frappe
from frappe import _


def validate(doc, method):
    """
    Validate Branch Master before save.

    Constraints:
    1. Only ONE active Branch Master per branch at a time
    2. New BM can only be created after previous one reaches 'Ordered' status
    3. Validate that items exist
    """
    # Constraint 1: Only one active BM per branch
    if doc.is_new():
        existing_active = frappe.db.get_value(
            "Branch Master",
            {
                "branch": doc.branch,
                "docstatus": ["in", [0, 1]],
                "status": ["not in", ["Ordered", "Cancelled"]],
                "name": ["!=", doc.name]
            },
            ["name", "status"],
            as_dict=True
        )
        if existing_active:
            frappe.throw(
                _("An active Branch Master ({0}) already exists for branch {1} with status '{2}'. "
                  "A new Branch Master can only be created after the existing one reaches 'Ordered' status.").format(
                    existing_active.name, doc.branch, existing_active.status
                ),
                title=_("Duplicate Branch Master")
            )

    # Validate branch is set
    if not doc.branch:
        frappe.throw(_("Branch is mandatory for Branch Master."))

    # Validate at least one item exists
    if not doc.items or len(doc.items) == 0:
        frappe.throw(_("Branch Master must have at least one item in the consolidated items table."))

    # Validate at least one source MR exists
    if not doc.source_material_requests or len(doc.source_material_requests) == 0:
        frappe.throw(_("Branch Master must have at least one source Material Request."))

    # Recalculate amounts for each item
    for item in doc.items:
        item.net_to_buy = max(0, (item.total_requested_qty or 0) - (item.available_qty or 0) - (item.inter_branch_fulfilled or 0))
        item.amount = (item.approved_qty or 0) * (item.rate or 0)


def before_submit(doc, method):
    """
    Before submitting a Branch Master:
    - Ensure all items have approved_qty set
    - Update status to 'Approved'
    """
    has_items_to_procure = False

    for item in doc.items:
        if (item.approved_qty or 0) > 0 and (item.net_to_buy or 0) > 0:
            has_items_to_procure = True

    if not has_items_to_procure:
        frappe.msgprint(
            _("No items require procurement (all items are either fulfilled via inter-branch transfer or have zero approved quantity)."),
            indicator="orange"
        )

    # Set status to Approved on submit
    doc.status = "Approved"
