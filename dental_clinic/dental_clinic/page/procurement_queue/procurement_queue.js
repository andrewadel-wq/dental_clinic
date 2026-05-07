frappe.pages['procurement-queue'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Procurement Queue',
        single_column: true
    });

    page.main.html(`
        <div id="procurement-queue-app">
            <div class="procurement-filters mb-3"></div>
            <div class="procurement-summary mb-3"></div>
            <div class="procurement-table-container"></div>
        </div>
    `);

    // Add "Export to PO" button
    page.set_primary_action('Export to PO', () => {
        page.procurement_queue.show_export_dialog();
    }, 'fa fa-file-text');

    page.procurement_queue = new ProcurementQueue(page);
};

class ProcurementQueue {
    constructor(page) {
        this.page = page;
        this.branch = '';
        this.search = '';
        this.selected_items = new Set();
        this.items = [];
        this.init();
    }

    init() {
        this.setup_filters();
        this.load_queue();
    }

    setup_filters() {
        const filters_area = this.page.main.find('.procurement-filters');
        filters_area.html(`
            <div class="row">
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">Branch</label>
                        <select class="form-control branch-filter">
                            <option value="">All Branches</option>
                        </select>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="form-group">
                        <label class="control-label">Search Item</label>
                        <input type="text" class="form-control search-filter" placeholder="Search by item code or name...">
                    </div>
                </div>
                <div class="col-md-2">
                    <div class="form-group">
                        <label class="control-label">&nbsp;</label>
                        <button class="btn btn-default btn-block refresh-btn">
                            <i class="fa fa-refresh"></i> Refresh
                        </button>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">Selected</label>
                        <div class="selected-count text-muted">0 items selected</div>
                    </div>
                </div>
            </div>
        `);

        // Load branches into dropdown
        frappe.call({
            method: 'frappe.client.get_list',
            args: { doctype: 'Branch', fields: ['name'], limit_page_length: 0 },
            callback: (r) => {
                const select = filters_area.find('.branch-filter');
                (r.message || []).forEach(b => {
                    select.append(`<option value="${b.name}">${b.name}</option>`);
                });
            }
        });

        // Events
        filters_area.find('.branch-filter').on('change', () => {
            this.branch = filters_area.find('.branch-filter').val();
            this.load_queue();
        });

        filters_area.find('.search-filter').on('input', frappe.utils.debounce(() => {
            this.search = filters_area.find('.search-filter').val();
            this.load_queue();
        }, 300));

        filters_area.find('.refresh-btn').on('click', () => this.load_queue());
    }

    async load_queue() {
        const container = this.page.main.find('.procurement-table-container');
        container.html('<div class="text-center p-4"><i class="fa fa-spinner fa-spin"></i> Loading procurement queue...</div>');

        try {
            const result = await frappe.call({
                method: 'dental_clinic.api.procurement_queue.get_procurement_queue',
                args: {
                    branch: this.branch,
                    search: this.search
                }
            });

            const data = result.message;
            this.items = data.items || [];

            // Render summary
            this.render_summary(data.summary || []);

            if (this.items.length === 0) {
                container.html('<div class="text-muted text-center p-4">No items pending procurement.</div>');
                return;
            }

            this.render_table(container);

        } catch (err) {
            container.html('<div class="text-danger p-4">Error loading queue: ' + (err.message || err) + '</div>');
        }
    }

    render_summary(summary) {
        const area = this.page.main.find('.procurement-summary');
        if (summary.length === 0) {
            area.html('');
            return;
        }

        let html = '<div class="row">';
        summary.forEach(bm => {
            html += `
                <div class="col-md-3 mb-2">
                    <div class="card p-2">
                        <strong>${bm.branch}</strong><br>
                        <small class="text-muted">BM: <a href="/app/branch-master/${bm.branch_master}">${bm.branch_master}</a></small><br>
                        <small>${bm.item_count} items | Status: ${bm.status}</small>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        area.html(html);
    }

    render_table(container) {
        let html = `
            <div class="table-responsive">
                <table class="table table-bordered table-hover table-sm">
                    <thead class="thead-light">
                        <tr>
                            <th><input type="checkbox" class="select-all-checkbox"></th>
                            <th>Item Code</th>
                            <th>Item Name</th>
                            <th>Branch</th>
                            <th>Branch Master</th>
                            <th class="text-right">Total Requested</th>
                            <th class="text-right">Available</th>
                            <th class="text-right">Net to Buy</th>
                            <th class="text-right">Approved Qty</th>
                            <th>UOM</th>
                            <th class="text-right">Rate</th>
                            <th class="text-right">Amount</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        this.items.forEach((item, idx) => {
            const checked = this.selected_items.has(idx) ? 'checked' : '';
            const net_class = item.net_to_buy > 0 ? 'text-danger font-weight-bold' : '';
            html += `
                <tr>
                    <td><input type="checkbox" class="item-checkbox" data-idx="${idx}" ${checked}></td>
                    <td>${item.item_code}</td>
                    <td>${item.item_name || ''}</td>
                    <td>${item.branch}</td>
                    <td><a href="/app/branch-master/${item.branch_master}">${item.branch_master}</a></td>
                    <td class="text-right">${item.total_requested_qty}</td>
                    <td class="text-right">${item.available_qty || 0}</td>
                    <td class="text-right ${net_class}">${item.net_to_buy}</td>
                    <td class="text-right">${item.approved_qty || item.net_to_buy}</td>
                    <td>${item.uom}</td>
                    <td class="text-right">${frappe.format(item.rate || 0, {fieldtype: 'Currency'})}</td>
                    <td class="text-right">${frappe.format(item.amount || 0, {fieldtype: 'Currency'})}</td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
        html += `<p class="text-muted">Total: ${this.items.length} items pending procurement</p>`;
        container.html(html);

        // Bind checkbox events
        container.find('.select-all-checkbox').on('change', (e) => {
            const checked = $(e.target).is(':checked');
            container.find('.item-checkbox').prop('checked', checked);
            if (checked) {
                this.items.forEach((_, idx) => this.selected_items.add(idx));
            } else {
                this.selected_items.clear();
            }
            this.update_selected_count();
        });

        container.find('.item-checkbox').on('change', (e) => {
            const idx = parseInt($(e.target).data('idx'));
            if ($(e.target).is(':checked')) {
                this.selected_items.add(idx);
            } else {
                this.selected_items.delete(idx);
            }
            this.update_selected_count();
        });
    }

    update_selected_count() {
        this.page.main.find('.selected-count').text(`${this.selected_items.size} items selected`);
    }

    show_export_dialog() {
        // Get selected items
        let selected = [];
        let branch_masters = new Set();

        if (this.selected_items.size === 0) {
            // If nothing selected, use all items
            selected = this.items;
            this.items.forEach(item => branch_masters.add(item.branch_master));
        } else {
            this.selected_items.forEach(idx => {
                selected.push(this.items[idx]);
                branch_masters.add(this.items[idx].branch_master);
            });
        }

        if (selected.length === 0) {
            frappe.msgprint('No items to export. Please load the queue first.');
            return;
        }

        // Build items preview
        let preview_html = '<table class="table table-sm table-bordered" style="font-size: 11px;">';
        preview_html += '<thead><tr><th>Item</th><th>Qty</th><th>UOM</th><th>Rate</th></tr></thead><tbody>';
        let total_amount = 0;
        selected.forEach(item => {
            const qty = item.approved_qty || item.net_to_buy;
            const amount = qty * (item.rate || 0);
            total_amount += amount;
            preview_html += `<tr><td>${item.item_code} - ${item.item_name}</td><td>${qty}</td><td>${item.uom}</td><td>${frappe.format(item.rate || 0, {fieldtype: 'Currency'})}</td></tr>`;
        });
        preview_html += `</tbody></table>`;
        preview_html += `<p><strong>Total: ${selected.length} items | Est. Amount: ${frappe.format(total_amount, {fieldtype: 'Currency'})}</strong></p>`;

        const d = new frappe.ui.Dialog({
            title: 'Export to Purchase Order',
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
                { fieldtype: 'Section Break', label: 'Items Preview' },
                {
                    fieldtype: 'HTML',
                    fieldname: 'items_preview',
                    options: preview_html
                }
            ],
            primary_action_label: 'Create Purchase Order',
            primary_action: async (values) => {
                d.hide();
                frappe.show_progress('Creating Purchase Order...', 0, 100);

                try {
                    const po_items = selected.map(item => ({
                        item_code: item.item_code,
                        item_name: item.item_name,
                        qty: item.approved_qty || item.net_to_buy,
                        rate: item.rate || 0,
                        uom: item.uom,
                    }));

                    const result = await frappe.call({
                        method: 'dental_clinic.api.procurement_queue.create_purchase_order',
                        args: {
                            supplier: values.supplier,
                            schedule_date: values.schedule_date,
                            items: JSON.stringify(po_items),
                            branch_masters: JSON.stringify(Array.from(branch_masters)),
                        }
                    });

                    frappe.hide_progress();
                    const msg = result.message;
                    frappe.show_alert({
                        message: `PO <a href="/app/purchase-order/${msg.purchase_order}">${msg.purchase_order}</a> created with ${msg.items_count} items`,
                        indicator: 'green'
                    }, 10);

                    // Refresh the queue
                    this.selected_items.clear();
                    this.update_selected_count();
                    this.load_queue();

                } catch (err) {
                    frappe.hide_progress();
                    frappe.msgprint({
                        title: 'Error',
                        message: err.message || 'Failed to create Purchase Order',
                        indicator: 'red'
                    });
                }
            }
        });
        d.show();
    }
}
