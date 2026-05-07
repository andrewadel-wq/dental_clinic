frappe.pages['nurse-acceptance'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Nurse Acceptance',
        single_column: true
    });

    page.main.html(`
        <div id="nurse-acceptance-app">
            <div class="acceptance-filters mb-3"></div>
            <div class="acceptance-pending-container"></div>
        </div>
    `);

    page.nurse_acceptance = new NurseAcceptance(page);
};

class NurseAcceptance {
    constructor(page) {
        this.page = page;
        this.branch = '';
        this.selected = new Set();
        this.init();
    }

    async init() {
        await this.get_user_branch();
        this.setup_filters();
        this.load_pending();
    }

    async get_user_branch() {
        const result = await frappe.call({
            method: 'dental_clinic.api.items_dashboard.get_user_branch'
        });
        this.user_data = result.message;
        if (!this.user_data.is_admin && this.user_data.branches.length === 1) {
            this.branch = this.user_data.branches[0];
        }
    }

    setup_filters() {
        const filters_area = this.page.main.find('.acceptance-filters');
        filters_area.html(`
            <div class="row align-items-end">
                <div class="col-md-3">
                    <div class="form-group mb-0">
                        <label class="control-label">Branch</label>
                        <select class="form-control branch-filter">
                            <option value="">All Branches</option>
                        </select>
                    </div>
                </div>
                <div class="col-md-2">
                    <button class="btn btn-default refresh-btn"><i class="fa fa-refresh"></i> Refresh</button>
                </div>
                <div class="col-md-4 text-right">
                    <button class="btn btn-success accept-selected-btn" disabled>
                        <i class="fa fa-check"></i> Accept Selected
                    </button>
                    <button class="btn btn-danger reject-selected-btn ml-2" disabled>
                        <i class="fa fa-times"></i> Reject Selected
                    </button>
                </div>
            </div>
        `);

        // Set default branch
        if (this.branch) {
            filters_area.find('.branch-filter').val(this.branch);
        }

        // Events
        filters_area.find('.branch-filter').on('change', () => {
            this.branch = filters_area.find('.branch-filter').val();
            this.load_pending();
        });
        filters_area.find('.refresh-btn').on('click', () => this.load_pending());
        filters_area.find('.accept-selected-btn').on('click', () => this.accept_selected());
        filters_area.find('.reject-selected-btn').on('click', () => this.reject_selected());
    }

    async load_pending() {
        const container = this.page.main.find('.acceptance-pending-container');
        container.html('<div class="text-center p-4"><i class="fa fa-spinner fa-spin"></i> Loading pending items...</div>');

        try {
            const result = await frappe.call({
                method: 'dental_clinic.api.nurse_acceptance.get_pending_acceptances',
                args: { branch: this.branch }
            });

            const items = result.message || [];
            if (items.length === 0) {
                container.html(`
                    <div class="text-center p-5">
                        <i class="fa fa-check-circle fa-3x text-success mb-3"></i>
                        <h5>All Clear!</h5>
                        <p class="text-muted">No items pending acceptance.</p>
                    </div>
                `);
                return;
            }

            this.render_pending_table(container, items);

        } catch (err) {
            container.html('<div class="text-danger p-4">Error: ' + (err.message || err) + '</div>');
        }
    }

    render_pending_table(container, items) {
        let html = `
            <div class="table-responsive">
                <table class="table table-bordered table-hover table-sm">
                    <thead class="thead-light">
                        <tr>
                            <th><input type="checkbox" class="select-all-cb"></th>
                            <th>Date</th>
                            <th>Item Code</th>
                            <th>Item Name</th>
                            <th class="text-right">Qty</th>
                            <th>From</th>
                            <th>Target Room</th>
                            <th>Doctor</th>
                            <th>Dispatched By</th>
                            <th>Stock Entry</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        items.forEach(item => {
            const checked = this.selected.has(item.stock_entry) ? 'checked' : '';
            html += `
                <tr>
                    <td><input type="checkbox" class="item-cb" data-se="${item.stock_entry}" ${checked}></td>
                    <td>${item.posting_date}</td>
                    <td><strong>${item.item_code}</strong></td>
                    <td>${item.item_name || ''}</td>
                    <td class="text-right">${item.qty}</td>
                    <td>${item.source_warehouse || ''}</td>
                    <td>${item.target_room || '<span class="text-warning">Not specified</span>'}</td>
                    <td>${item.doctor || ''}</td>
                    <td>${item.dispatched_by_name}</td>
                    <td><a href="/app/stock-entry/${item.stock_entry}">${item.stock_entry}</a></td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
        html += `<p class="text-muted">${items.length} item(s) pending acceptance</p>`;
        container.html(html);

        // Bind events
        container.find('.select-all-cb').on('change', (e) => {
            const checked = $(e.target).is(':checked');
            container.find('.item-cb').prop('checked', checked);
            this.selected.clear();
            if (checked) {
                items.forEach(item => this.selected.add(item.stock_entry));
            }
            this.update_buttons();
        });

        container.find('.item-cb').on('change', (e) => {
            const se = $(e.target).data('se');
            if ($(e.target).is(':checked')) {
                this.selected.add(se);
            } else {
                this.selected.delete(se);
            }
            this.update_buttons();
        });
    }

    update_buttons() {
        const has_selection = this.selected.size > 0;
        this.page.main.find('.accept-selected-btn').prop('disabled', !has_selection);
        this.page.main.find('.reject-selected-btn').prop('disabled', !has_selection);
    }

    async accept_selected() {
        if (this.selected.size === 0) return;

        frappe.confirm(
            `Accept ${this.selected.size} item(s)?`,
            async () => {
                frappe.show_progress('Accepting items...', 0, 100);

                try {
                    const result = await frappe.call({
                        method: 'dental_clinic.api.nurse_acceptance.accept_items',
                        args: {
                            stock_entries: JSON.stringify(Array.from(this.selected))
                        }
                    });

                    frappe.hide_progress();
                    const msg = result.message;

                    if (msg.errors && msg.errors.length > 0) {
                        frappe.msgprint({
                            title: 'Partial Success',
                            message: `${msg.accepted.length} accepted, ${msg.errors.length} failed.<br>Errors: ${msg.errors.map(e => e.error).join('<br>')}`,
                            indicator: 'orange'
                        });
                    } else {
                        frappe.show_alert({ message: msg.message, indicator: 'green' }, 5);
                    }

                    this.selected.clear();
                    this.update_buttons();
                    this.load_pending();

                } catch (err) {
                    frappe.hide_progress();
                    frappe.msgprint({ title: 'Error', message: err.message || 'Failed', indicator: 'red' });
                }
            }
        );
    }

    async reject_selected() {
        if (this.selected.size === 0) return;

        const d = new frappe.ui.Dialog({
            title: 'Reject Items',
            fields: [
                {
                    label: 'Reason for Rejection',
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    reqd: 1,
                    description: 'Please provide a reason for rejecting these items'
                }
            ],
            primary_action_label: 'Reject',
            primary_action: async (values) => {
                d.hide();
                frappe.show_progress('Rejecting items...', 0, 100);

                try {
                    const result = await frappe.call({
                        method: 'dental_clinic.api.nurse_acceptance.reject_items',
                        args: {
                            stock_entries: JSON.stringify(Array.from(this.selected)),
                            reason: values.reason
                        }
                    });

                    frappe.hide_progress();
                    const msg = result.message;
                    frappe.show_alert({ message: msg.message, indicator: 'orange' }, 5);

                    this.selected.clear();
                    this.update_buttons();
                    this.load_pending();

                } catch (err) {
                    frappe.hide_progress();
                    frappe.msgprint({ title: 'Error', message: err.message || 'Failed', indicator: 'red' });
                }
            }
        });
        d.show();
    }
}
