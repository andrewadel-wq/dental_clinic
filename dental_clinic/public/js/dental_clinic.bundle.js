/**
 * Dental Clinic IMS - Client-Side Enhancements Bundle
 *
 * This file contains all client-side customizations that enhance the standard
 * ERPNext forms for the dental clinic workflow.
 *
 * Sections:
 * 1. Material Request Form Enhancements
 * 2. Branch Master Form Enhancements
 * 3. Purchase Order Form Enhancements (CEO)
 * 4. Global Utilities
 */

// =============================================================================
// 1. MATERIAL REQUEST FORM ENHANCEMENTS
// =============================================================================

frappe.ui.form.on('Material Request', {
    refresh: function(frm) {
        // Hide custom_doctor (free text) - use custom_doctor_name (Link) instead
        frm.toggle_display('custom_doctor', false);

        // Make custom_doctor_name prominent
        if (frm.fields_dict.custom_doctor_name) {
            frm.set_df_property('custom_doctor_name', 'bold', 1);
        }

        // Show branch info in form header
        if (frm.doc.custom_branch) {
            frm.dashboard.add_indicator(
                __('Branch: {0}', [frm.doc.custom_branch]),
                'blue'
            );
        }

        // Show room info
        if (frm.doc.custom_room) {
            frm.dashboard.add_indicator(
                __('Room: {0}', [frm.doc.custom_room]),
                'green'
            );
        }
    },

    validate: function(frm) {
        // Validate integer quantities on all items
        let has_decimal = false;
        (frm.doc.items || []).forEach(function(item) {
            if (item.qty && item.qty !== Math.floor(item.qty)) {
                has_decimal = true;
                frappe.model.set_value(item.doctype, item.name, 'qty', Math.round(item.qty));
            }
        });
        if (has_decimal) {
            frappe.show_alert({
                message: __('Decimal quantities have been rounded to whole numbers.'),
                indicator: 'orange'
            });
        }
    },

    custom_branch: function(frm) {
        // When branch changes, filter room warehouse to show only rooms in that branch
        if (frm.doc.custom_branch) {
            frm.set_query('custom_room', function() {
                return {
                    filters: {
                        'parent_warehouse': frm.doc.custom_branch + ' - DNA',
                        'is_group': 0,
                        'name': ['like', '%Rm%']
                    }
                };
            });
        }
    }
});

// Material Request Item - enforce integer qty and show dual UOM
frappe.ui.form.on('Material Request Item', {
    qty: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // Enforce integer
        if (row.qty && row.qty !== Math.floor(row.qty)) {
            frappe.model.set_value(cdt, cdn, 'qty', Math.round(row.qty));
            frappe.show_alert({
                message: __('Row {0}: Quantity rounded to whole number.', [row.idx]),
                indicator: 'orange'
            });
        }
    },

    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.item_code) {
            // Auto-fetch conversion factor info for dual UOM display
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'UOM Conversion Detail',
                    filters: { parent: row.item_code, parenttype: 'Item' },
                    fields: ['uom', 'conversion_factor'],
                    limit_page_length: 10
                },
                callback: function(r) {
                    if (r.message && r.message.length > 1) {
                        // Item has multiple UOMs - show info
                        let uom_info = r.message.map(u =>
                            `${u.uom} (1 = ${u.conversion_factor} ${row.stock_uom || 'Nos'})`
                        ).join(', ');
                        // Store for display
                        frappe.model.set_value(cdt, cdn, 'custom_uom_info', uom_info);
                    }
                }
            });
        }
    }
});


// =============================================================================
// 2. BRANCH MASTER FORM ENHANCEMENTS
// =============================================================================

frappe.ui.form.on('Branch Master', {
    refresh: function(frm) {
        // Add action buttons for Draft documents
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Refresh Stock Levels'), function() {
                frappe.call({
                    method: 'dental_clinic.api.consolidation.refresh_branch_master_stock',
                    args: { branch_master: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Refreshing stock levels...'),
                    callback: function(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Re-consolidate'), function() {
                frappe.confirm(
                    __('This will re-fetch all approved MRs for this branch and rebuild the items table. Continue?'),
                    function() {
                        frappe.call({
                            method: 'dental_clinic.api.consolidation.reconsolidate_branch_master',
                            args: { branch_master: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Re-consolidating...'),
                            callback: function(r) {
                                if (r.message) {
                                    frappe.show_alert({
                                        message: r.message.message,
                                        indicator: 'green'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }, __('Actions'));

            frm.add_custom_button(__('Consolidate New MRs'), function() {
                frappe.call({
                    method: 'dental_clinic.api.consolidation.consolidate_branch_mrs',
                    args: {
                        branch: frm.doc.branch,
                        posting_date: frappe.datetime.now_date()
                    },
                    freeze: true,
                    freeze_message: __('Consolidating new Material Requests...'),
                    callback: function(r) {
                        if (r.message) {
                            frappe.show_alert({
                                message: __('Consolidated {0} MRs with {1} items', [r.message.mr_count, r.message.items_count]),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));
        }

        // Add "Create Purchase Order" button for Submitted documents
        if (frm.doc.docstatus === 1 && frm.doc.status !== 'Ordered') {
            frm.add_custom_button(__('Create Purchase Order'), function() {
                show_create_po_dialog(frm);
            }, __('Actions'));
        }

        // Show status indicator
        if (frm.doc.status) {
            let color = {
                'Draft': 'orange',
                'Pending Review': 'yellow',
                'Approved': 'blue',
                'Partially Ordered': 'purple',
                'Ordered': 'green',
                'Cancelled': 'red'
            }[frm.doc.status] || 'grey';

            frm.dashboard.add_indicator(frm.doc.status, color);
        }
    }
});

function show_create_po_dialog(frm) {
    let items = (frm.doc.items || []).filter(item => (item.net_to_buy || 0) > 0);

    if (items.length === 0) {
        frappe.msgprint(__('No items require procurement (all items have sufficient stock).'));
        return;
    }

    // Build items preview
    let preview_html = '<table class="table table-bordered table-sm" style="font-size: 12px;">';
    preview_html += '<thead><tr><th>Item</th><th class="text-right">Net to Buy</th><th>UOM</th></tr></thead><tbody>';
    items.forEach(item => {
        preview_html += `<tr><td>${item.item_code} - ${item.item_name}</td><td class="text-right">${item.net_to_buy}</td><td>${item.uom || 'Nos'}</td></tr>`;
    });
    preview_html += '</tbody></table>';
    preview_html += `<p class="text-muted">Total: ${items.length} items to order</p>`;

    let d = new frappe.ui.Dialog({
        title: __('Create Purchase Order'),
        size: 'large',
        fields: [
            {
                label: 'Supplier',
                fieldname: 'supplier',
                fieldtype: 'Link',
                options: 'Supplier',
                reqd: 1,
            },
            {
                label: 'Required By Date',
                fieldname: 'schedule_date',
                fieldtype: 'Date',
                reqd: 1,
                default: frappe.datetime.add_days(frappe.datetime.now_date(), 7),
            },
            { fieldtype: 'Section Break', label: 'Items to Order' },
            {
                fieldtype: 'HTML',
                fieldname: 'items_html',
                options: preview_html
            }
        ],
        primary_action_label: __('Create PO'),
        primary_action: function(values) {
            d.hide();
            frappe.show_progress(__('Creating Purchase Order...'), 0, 100);

            let po_items = items.map(item => ({
                item_code: item.item_code,
                item_name: item.item_name,
                qty: item.net_to_buy,
                rate: item.rate || 0,
                uom: item.uom || 'Nos',
            }));

            frappe.call({
                method: 'dental_clinic.api.procurement_queue.create_purchase_order',
                args: {
                    supplier: values.supplier,
                    schedule_date: values.schedule_date,
                    items: JSON.stringify(po_items),
                    branch_masters: JSON.stringify([frm.doc.name]),
                },
                callback: function(r) {
                    frappe.hide_progress();
                    if (r.message) {
                        frappe.show_alert({
                            message: __('Purchase Order {0} created with {1} items',
                                [`<a href="/app/purchase-order/${r.message.purchase_order}">${r.message.purchase_order}</a>`, r.message.items_count]),
                            indicator: 'green'
                        }, 10);
                        frm.reload_doc();
                    }
                },
                error: function() {
                    frappe.hide_progress();
                }
            });
        }
    });
    d.show();
}


// =============================================================================
// 3. PURCHASE ORDER FORM ENHANCEMENTS (CEO)
// =============================================================================

frappe.ui.form.on('Purchase Order', {
    refresh: function(frm) {
        // Add "Check Procurement Details" button for CEO
        if (frappe.user_roles.includes('CEO') || frappe.user_roles.includes('System Manager')) {
            frm.add_custom_button(__('Check Procurement Details'), function() {
                show_procurement_details_dialog(frm);
            });
        }

        // Show auto-approval threshold info
        if (frm.doc.grand_total && frm.doc.grand_total < 5000) {
            frm.dashboard.add_indicator(
                __('Below AED 5,000 threshold (auto-approval eligible)'),
                'green'
            );
        }
    },

    validate: function(frm) {
        // Validate integer quantities
        let has_decimal = false;
        (frm.doc.items || []).forEach(function(item) {
            if (item.qty && item.qty !== Math.floor(item.qty)) {
                has_decimal = true;
                frappe.model.set_value(item.doctype, item.name, 'qty', Math.round(item.qty));
            }
        });
        if (has_decimal) {
            frappe.show_alert({
                message: __('Decimal quantities have been rounded to whole numbers.'),
                indicator: 'orange'
            });
        }
    }
});

function show_procurement_details_dialog(frm) {
    frappe.call({
        method: 'dental_clinic.api.ceo_dashboard.get_procurement_details',
        args: { po_name: frm.doc.name },
        freeze: true,
        freeze_message: __('Loading procurement details...'),
        callback: function(r) {
            if (!r.message) return;

            let data = r.message;
            let details = data.details;
            let summary = data.summary;

            // Build HTML
            let html = `
                <div class="procurement-details">
                    <div class="row mb-3">
                        <div class="col-md-3"><strong>Total Items:</strong> ${summary.total_items}</div>
                        <div class="col-md-3"><strong>Total Amount:</strong> AED ${(summary.total_amount || 0).toFixed(2)}</div>
                        <div class="col-md-3"><strong>Items with Buffer:</strong> ${summary.items_with_buffer}</div>
                        <div class="col-md-3"><strong>Price Alerts:</strong> <span class="${summary.items_price_higher > 0 ? 'text-danger' : ''}">${summary.items_price_higher}</span></div>
                    </div>
                    <hr>
            `;

            details.forEach(item => {
                html += `<div class="item-detail-section mb-3 p-2" style="border: 1px solid #eee; border-radius: 4px;">`;
                html += `<h6><strong>${item.item_code}</strong> - ${item.item_name} | Qty: ${item.qty} | Rate: AED ${(item.rate || 0).toFixed(2)}</h6>`;

                // Buffer analysis
                if (item.buffer_analysis && item.buffer_analysis.status) {
                    let buf = item.buffer_analysis;
                    let buf_color = buf.difference > 0 ? 'orange' : (buf.difference < 0 ? 'red' : 'green');
                    html += `<p><small><strong>Buffer:</strong> <span style="color: ${buf_color}">${buf.status}</span> (Requested: ${buf.total_requested}, Available: ${buf.available_stock}, Net: ${buf.net_required}, Ordering: ${buf.to_buy})</small></p>`;
                }

                // Price analysis
                if (item.price_analysis) {
                    let pa = item.price_analysis;
                    let price_color = pa.status === 'Higher' ? 'red' : (pa.status === 'Lower' ? 'green' : 'black');
                    html += `<p><small><strong>Price:</strong> Current AED ${pa.current_rate} vs Avg AED ${pa.avg_historical_rate} (<span style="color: ${price_color}">${pa.variance_pct > 0 ? '+' : ''}${pa.variance_pct}%</span>)</small></p>`;
                }

                // Requestors
                if (item.requestors && item.requestors.length > 0) {
                    html += '<table class="table table-sm" style="font-size: 11px;"><thead><tr><th>Nurse</th><th>Doctor</th><th>Room</th><th>Qty</th></tr></thead><tbody>';
                    item.requestors.forEach(req => {
                        html += `<tr><td>${req.nurse}</td><td>${req.doctor}</td><td>${req.room}</td><td>${req.qty}</td></tr>`;
                    });
                    html += '</tbody></table>';
                }

                html += '</div>';
            });

            html += '</div>';

            let d = new frappe.ui.Dialog({
                title: __('Procurement Details - {0}', [frm.doc.name]),
                size: 'extra-large',
                fields: [{ fieldtype: 'HTML', fieldname: 'details_html', options: html }],
                primary_action_label: __('Close'),
                primary_action: () => d.hide()
            });
            d.show();
        }
    });
}


// =============================================================================
// 4. GLOBAL UTILITIES
// =============================================================================

// Add navigation shortcuts to the sidebar
$(document).ready(function() {
    // Add custom pages to the module sidebar (if dental_clinic module is visible)
    if (frappe.boot && frappe.boot.user && frappe.boot.user.roles) {
        let roles = frappe.boot.user.roles || [];

        // Items Dashboard - for NIC, Store Keeper, Head Nurse
        if (roles.includes('Nurse In Charge') || roles.includes('Store Keeper') || roles.includes('Head Nurse') || roles.includes('System Manager')) {
            frappe.router.on('change', function() {
                // Add shortcut if on Stock module
            });
        }
    }
});

// Branch Master List View - Add Consolidate All button
frappe.listview_settings['Branch Master'] = {
    onload: function(listview) {
        listview.page.add_inner_button(__('Consolidate All Branches'), function() {
            frappe.confirm(
                __('This will consolidate all Approved Material Requests into Branch Masters for each branch. Continue?'),
                function() {
                    frappe.call({
                        method: 'dental_clinic.api.consolidation.get_consolidation_status',
                        callback: function(r) {
                            let status = r.message || [];
                            let branches_needing_consolidation = status.filter(s => s.needs_consolidation);

                            if (branches_needing_consolidation.length === 0) {
                                frappe.msgprint(__('No branches have pending Material Requests to consolidate.'));
                                return;
                            }

                            let processed = 0;
                            let total = branches_needing_consolidation.length;

                            frappe.show_progress(__('Consolidating...'), 0, total);

                            branches_needing_consolidation.forEach(function(branch_info) {
                                frappe.call({
                                    method: 'dental_clinic.api.consolidation.consolidate_branch_mrs',
                                    args: { branch: branch_info.branch },
                                    async: false,
                                    callback: function() {
                                        processed++;
                                        frappe.show_progress(__('Consolidating...'), processed, total, branch_info.branch);
                                        if (processed === total) {
                                            frappe.hide_progress();
                                            frappe.msgprint(__('Consolidation complete for {0} branches.', [total]));
                                            listview.refresh();
                                        }
                                    }
                                });
                            });
                        }
                    });
                }
            );
        });
    },

    get_indicator: function(doc) {
        if (doc.status === 'Draft') return [__('Draft'), 'orange', 'status,=,Draft'];
        if (doc.status === 'Pending Review') return [__('Pending Review'), 'yellow', 'status,=,Pending Review'];
        if (doc.status === 'Approved') return [__('Approved'), 'blue', 'status,=,Approved'];
        if (doc.status === 'Partially Ordered') return [__('Partially Ordered'), 'purple', 'status,=,Partially Ordered'];
        if (doc.status === 'Ordered') return [__('Ordered'), 'green', 'status,=,Ordered'];
        if (doc.status === 'Cancelled') return [__('Cancelled'), 'red', 'status,=,Cancelled'];
    }
};
