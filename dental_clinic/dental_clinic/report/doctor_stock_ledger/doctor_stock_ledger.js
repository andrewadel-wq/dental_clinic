frappe.query_reports["Doctor Stock Ledger"] = {
    "filters": [
        {
            "fieldname": "doctor",
            "label": __("Doctor"),
            "fieldtype": "Link",
            "options": "Doctor",
            "width": 150
        },
        {
            "fieldname": "item_code",
            "label": __("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 150
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "width": 100
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "width": 100
        },
        {
            "fieldname": "branch",
            "label": __("Branch"),
            "fieldtype": "Data",
            "width": 100,
            "description": "Filter by branch code (SS, Mir, Mar, Jum)"
        }
    ]
};
