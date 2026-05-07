frappe.pages['items-dashboard'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Items Dashboard',
        single_column: true
    });

    page.main.html(`
        <div id="items-dashboard-app">
            <div class="items-dashboard-filters mb-4"></div>
            <div class="items-dashboard-tabs">
                <ul class="nav nav-tabs" role="tablist">
                    <li class="nav-item">
                        <a class="nav-link active" data-toggle="tab" href="#items-tab" role="tab">Items View</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-toggle="tab" href="#rooms-tab" role="tab">Rooms View</a>
                    </li>
                </ul>
                <div class="tab-content mt-3">
                    <div class="tab-pane active" id="items-tab" role="tabpanel">
                        <div class="items-table-container"></div>
                    </div>
                    <div class="tab-pane" id="rooms-tab" role="tabpanel">
                        <div class="rooms-table-container"></div>
                    </div>
                </div>
            </div>
        </div>
    `);

    new ItemsDashboard(page);
};

class ItemsDashboard {
    constructor(page) {
        this.page = page;
        this.branch = null;
        this.search = '';
        this.init();
    }

    async init() {
        await this.get_user_branch();
        this.setup_filters();
        this.load_items();
        this.load_rooms();
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
        const filters_area = this.page.main.find('.items-dashboard-filters');

        // Branch filter
        let branch_options = ['All Branches'];
        if (this.user_data.is_admin) {
            branch_options = branch_options.concat(this.user_data.branches.map(b => b.name));
        } else {
            branch_options = branch_options.concat(this.user_data.branches);
        }

        const branch_html = `
            <div class="row">
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">Branch</label>
                        <select class="form-control branch-filter">
                            ${branch_options.map(b => `<option value="${b === 'All Branches' ? '' : (b.name || b)}">${b.name || b}</option>`).join('')}
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
                        <button class="btn btn-primary btn-block refresh-btn">Refresh</button>
                    </div>
                </div>
            </div>
        `;
        filters_area.html(branch_html);

        // Set default branch for non-admin users
        if (this.branch) {
            filters_area.find('.branch-filter').val(this.branch);
        }

        // Event handlers
        filters_area.find('.branch-filter').on('change', () => {
            this.branch = filters_area.find('.branch-filter').val();
            this.load_items();
            this.load_rooms();
        });

        filters_area.find('.search-filter').on('input', frappe.utils.debounce(() => {
            this.search = filters_area.find('.search-filter').val();
            this.load_items();
        }, 300));

        filters_area.find('.refresh-btn').on('click', () => {
            this.load_items();
            this.load_rooms();
        });
    }

    async load_items() {
        const container = this.page.main.find('.items-table-container');
        container.html('<div class="text-center"><i class="fa fa-spinner fa-spin"></i> Loading...</div>');

        try {
            const result = await frappe.call({
                method: 'dental_clinic.api.items_dashboard.get_items_view',
                args: {
                    branch: this.branch || '',
                    search: this.search || ''
                }
            });

            const items = result.message || [];
            if (items.length === 0) {
                container.html('<div class="text-muted text-center p-4">No items found with pending requests.</div>');
                return;
            }

            let html = `
                <div class="table-responsive">
                    <table class="table table-bordered table-hover table-sm">
                        <thead class="thead-light">
                            <tr>
                                <th>Item Code</th>
                                <th>Item Name</th>
                                <th>Branch</th>
                                <th class="text-right">Total Requested</th>
                                <th class="text-right">Moved</th>
                                <th class="text-right">Remaining</th>
                                <th class="text-right">Available Stock</th>
                                <th class="text-right">MR Count</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            items.forEach(item => {
                const remaining_class = item.remaining_qty > item.available_stock ? 'text-danger font-weight-bold' : '';
                html += `
                    <tr class="item-row" data-item-code="${item.item_code}" data-branch="${item.branch}">
                        <td><a href="#" class="item-detail-link">${item.item_code}</a></td>
                        <td>${item.item_name || ''}</td>
                        <td>${item.branch || ''}</td>
                        <td class="text-right">${item.total_requested_qty}</td>
                        <td class="text-right">${item.total_moved_qty || 0}</td>
                        <td class="text-right ${remaining_class}">${item.remaining_qty || 0}</td>
                        <td class="text-right">${item.available_stock || 0}</td>
                        <td class="text-right">${item.mr_count}</td>
                        <td>
                            <button class="btn btn-xs btn-primary dispatch-btn" data-item="${item.item_code}">
                                Dispatch
                            </button>
                        </td>
                    </tr>
                `;
            });

            html += '</tbody></table></div>';
            html += `<p class="text-muted">Total: ${items.length} items</p>`;
            container.html(html);

            // Bind events
            container.find('.item-detail-link').on('click', (e) => {
                e.preventDefault();
                const row = $(e.target).closest('.item-row');
                this.show_item_detail(row.data('item-code'), row.data('branch'));
            });

            container.find('.dispatch-btn').on('click', (e) => {
                const item_code = $(e.target).data('item');
                this.show_dispatch_dialog(item_code);
            });

        } catch (err) {
            container.html('<div class="text-danger p-4">Error loading items: ' + (err.message || err) + '</div>');
        }
    }

    async load_rooms() {
        const container = this.page.main.find('.rooms-table-container');
        container.html('<div class="text-center"><i class="fa fa-spinner fa-spin"></i> Loading...</div>');

        try {
            const result = await frappe.call({
                method: 'dental_clinic.api.items_dashboard.get_rooms_view',
                args: { branch: this.branch || '' }
            });

            const rooms = result.message || [];
            if (rooms.length === 0) {
                container.html('<div class="text-muted text-center p-4">No rooms with pending requests.</div>');
                return;
            }

            let html = `
                <div class="table-responsive">
                    <table class="table table-bordered table-hover table-sm">
                        <thead class="thead-light">
                            <tr>
                                <th>Room</th>
                                <th>Branch</th>
                                <th class="text-right">MR Count</th>
                                <th class="text-right">Items Count</th>
                                <th class="text-right">Total Qty</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            rooms.forEach(room => {
                html += `
                    <tr>
                        <td>${room.room || 'Unspecified'}</td>
                        <td>${room.branch || ''}</td>
                        <td class="text-right">${room.mr_count}</td>
                        <td class="text-right">${room.item_count}</td>
                        <td class="text-right">${room.total_qty}</td>
                    </tr>
                `;
            });

            html += '</tbody></table></div>';
            container.html(html);

        } catch (err) {
            container.html('<div class="text-danger p-4">Error loading rooms: ' + (err.message || err) + '</div>');
        }
    }

    async show_item_detail(item_code, branch) {
        const result = await frappe.call({
            method: 'dental_clinic.api.items_dashboard.get_item_detail',
            args: { item_code: item_code, branch: branch || '' }
        });

        const data = result.message;
        if (!data) return;

        let stock_html = '<h6>Available Stock by Warehouse:</h6>';
        if (data.stock_by_warehouse.length > 0) {
            stock_html += '<table class="table table-sm table-bordered"><thead><tr><th>Warehouse</th><th class="text-right">Available</th></tr></thead><tbody>';
            data.stock_by_warehouse.forEach(s => {
                stock_html += `<tr><td>${s.warehouse}</td><td class="text-right">${s.available_qty}</td></tr>`;
            });
            stock_html += '</tbody></table>';
        } else {
            stock_html += '<p class="text-muted">No stock available in any warehouse.</p>';
        }

        let mr_html = '<h6 class="mt-3">Requesting Material Requests:</h6>';
        if (data.requesting_mrs.length > 0) {
            mr_html += '<table class="table table-sm table-bordered"><thead><tr><th>MR#</th><th>Nurse</th><th>Doctor</th><th>Room</th><th class="text-right">Requested</th><th class="text-right">Remaining</th></tr></thead><tbody>';
            data.requesting_mrs.forEach(mr => {
                mr_html += `<tr>
                    <td><a href="/app/material-request/${mr.mr_name}">${mr.mr_name}</a></td>
                    <td>${mr.requested_by_name}</td>
                    <td>${mr.doctor || 'General'}</td>
                    <td>${mr.room || ''}</td>
                    <td class="text-right">${mr.requested_qty}</td>
                    <td class="text-right">${mr.remaining_qty}</td>
                </tr>`;
            });
            mr_html += '</tbody></table>';
        } else {
            mr_html += '<p class="text-muted">No pending requests.</p>';
        }

        const d = new frappe.ui.Dialog({
            title: `${item_code} - ${data.item_info.item_name}`,
            size: 'large',
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'detail_html',
                    options: `
                        <div class="item-detail-content">
                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <strong>Item Group:</strong> ${data.item_info.item_group || ''}
                                </div>
                                <div class="col-md-6">
                                    <strong>Stock UOM:</strong> ${data.item_info.stock_uom || 'Nos'}
                                </div>
                            </div>
                            ${stock_html}
                            ${mr_html}
                        </div>
                    `
                }
            ],
            primary_action_label: 'Dispatch',
            primary_action: () => {
                d.hide();
                this.show_dispatch_dialog(item_code);
            }
        });
        d.show();
    }

    show_dispatch_dialog(item_code) {
        const d = new frappe.ui.Dialog({
            title: `Dispatch: ${item_code}`,
            fields: [
                {
                    label: 'Source Warehouse',
                    fieldname: 'source_warehouse',
                    fieldtype: 'Link',
                    options: 'Warehouse',
                    reqd: 1,
                    description: 'Where to take the item from (must have stock)',
                    get_query: () => ({
                        filters: { is_group: 0, company: 'Drs. Nicolas & Asp' }
                    })
                },
                {
                    label: 'Target Room/Warehouse',
                    fieldname: 'target_warehouse',
                    fieldtype: 'Link',
                    options: 'Warehouse',
                    reqd: 1,
                    description: 'Where to send the item (room)',
                    get_query: () => ({
                        filters: { is_group: 0, company: 'Drs. Nicolas & Asp' }
                    })
                },
                { fieldtype: 'Column Break' },
                {
                    label: 'Quantity',
                    fieldname: 'qty',
                    fieldtype: 'Int',
                    reqd: 1,
                    description: 'Whole numbers only'
                },
                {
                    label: 'Doctor',
                    fieldname: 'doctor',
                    fieldtype: 'Link',
                    options: 'Doctor',
                    description: 'Doctor this dispatch is for (optional)'
                },
                { fieldtype: 'Section Break' },
                {
                    label: 'Link to Material Request (optional)',
                    fieldname: 'material_request',
                    fieldtype: 'Link',
                    options: 'Material Request',
                    description: 'If dispatching against a specific MR'
                }
            ],
            primary_action_label: 'Dispatch',
            primary_action: async (values) => {
                if (values.qty <= 0) {
                    frappe.msgprint('Quantity must be a positive number');
                    return;
                }
                if (values.qty !== Math.floor(values.qty)) {
                    frappe.msgprint('Decimal quantities are not allowed. Please use whole numbers.');
                    return;
                }

                d.hide();
                frappe.show_progress('Dispatching...', 0, 100);

                try {
                    const result = await frappe.call({
                        method: 'dental_clinic.api.items_dashboard.dispatch_item',
                        args: {
                            item_code: item_code,
                            source_warehouse: values.source_warehouse,
                            target_warehouse: values.target_warehouse,
                            qty: values.qty,
                            doctor: values.doctor || '',
                            material_request: values.material_request || '',
                        }
                    });

                    frappe.hide_progress();
                    frappe.show_alert({
                        message: result.message.message,
                        indicator: 'green'
                    }, 5);

                    // Refresh the items list
                    this.load_items();

                } catch (err) {
                    frappe.hide_progress();
                    frappe.msgprint({
                        title: 'Dispatch Failed',
                        message: err.message || 'An error occurred during dispatch.',
                        indicator: 'red'
                    });
                }
            }
        });
        d.show();
    }
}
