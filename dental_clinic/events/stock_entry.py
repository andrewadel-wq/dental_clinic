import frappe
from frappe import _


def on_submit(doc, method):
    """
    After a Stock Entry is submitted:
    1. If Material Transfer (dispatch): update custom_moved_quantity on source MR items
    2. Track doctor information for Doctor Stock Ledger
    """
    if doc.stock_entry_type == "Material Transfer":
        handle_material_transfer(doc)
    elif doc.stock_entry_type == "Material Issue":
        handle_material_issue(doc)


def handle_material_transfer(doc):
    """
    When items are dispatched (Material Transfer):
    - Update custom_moved_quantity on the source MR Item
    - Update custom_remaining_quantity on the source MR Item
    """
    # Check if this transfer is linked to a Material Request
    for item in doc.items:
        if item.material_request and item.material_request_item:
            # Update the MR Item's moved and remaining quantities
            mr_item = frappe.get_doc("Material Request Item", item.material_request_item)
            current_moved = mr_item.custom_moved_quantity or 0
            new_moved = current_moved + item.qty

            frappe.db.set_value(
                "Material Request Item",
                item.material_request_item,
                {
                    "custom_moved_quantity": new_moved,
                    "custom_remaining_quantity": max(0, mr_item.qty - new_moved)
                }
            )


def handle_material_issue(doc):
    """
    When items are consumed (Material Issue):
    - This is tracked via the Material Usage page
    - The PX File Number and Doctor are stored as custom fields on the Stock Entry
    """
    # Nothing additional needed here - the Stock Entry itself stores the consumption data
    # Doctor Stock Ledger queries Stock Entry directly
    pass
