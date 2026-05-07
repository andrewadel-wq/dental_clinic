# Dental Clinic IMS

Custom Frappe application for dental clinic inventory management at Drs. Nicolas & Asp.

## Features

- **Branch Master Consolidation**: Automatically consolidates approved Material Requests into Branch Masters per branch
- **Items Dashboard**: Real-time view of all requested items with dispatch functionality
- **Procurement Queue**: Consolidated view of items needing purchase with Export to PO
- **Material Usage**: Room-based consumption tracking with mandatory PX File numbers
- **Nurse Acceptance**: Transit-based acceptance flow for dispatched items
- **Doctor Stock Ledger**: Per-doctor stock movement report with running balance
- **CEO Enhancements**: Procurement details dialog, price history, auto-approval threshold

## Installation

```bash
bench get-app https://github.com/YOUR_ORG/dental_clinic.git
bench --site your-site install-app dental_clinic
```

## Configuration

The app hooks into existing ERPNext doctypes (Material Request, Purchase Order, Stock Entry, Branch Master) via document events defined in `hooks.py`.

## License

MIT
