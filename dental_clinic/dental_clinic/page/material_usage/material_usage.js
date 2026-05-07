frappe.pages['material-usage'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Material Usage',
        single_column: true
    });

    page.main.html(`
        <div id="material-usage-app">
            <div class="usage-header mb-4"></div>
            <div class="usage-tabs">
                <ul class="nav nav-tabs" role="tablist">
                    <li class="nav-item">
                        <a class="nav-link active" data-toggle="tab" href="#record-tab" role="tab">Record Usage</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" data-toggle="tab" href="#history-tab" role="tab">Usage History</a>
                    </li>
                </ul>
                <div class="tab-content mt-3">
                    <div class="tab-pane active" id="record-tab" role="tabpanel">
                        <div class="record-usage-container"></div>
                    </div>
                    <div class="tab-pane" id="history-tab" role="tabpanel">
                        <div class="usage-history-container"></div>
                    </div>
                </div>
            </div>
        </div>
    `);

    page.material_usage = new MaterialUsage(page);
};

class MaterialUsage {
    constructor(page) {
        this.page = page;
        this.branch = '';
        this.room = '';
        this.cart = []; // Items to be consumed
        this.init();
    }

    async init() {
        await this.get_user_branch();
        this.render_header();
        this.render_record_form();
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

    render_header() {
        const header = this.page.main.find('.usage-header');
        header.html(`
            <div class="row">
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">Room</label>
                        <select class="form-control room-select">
                            <option value="">Select Room...</option>
                        </select>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">PX File Number <span class="text-danger">*</span></label>
                        <input type="text" class="form-control px-file-input" placeholder="Patient file number...">
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="form-group">
                        <label class="control-label">Doctor</label>
                        <div class="doctor-field"></div>
                    </div>
                </div>
            </div>
        `);

        // Load rooms
        this.load_rooms();

        // Setup doctor link field
        const doctor_wrapper = header.find('.doctor-field');
        this.doctor_field = frappe.ui.form.make_control({
            df: {
                fieldname: 'doctor',
                fieldtype: 'Link',
                options: 'Doctor',
                placeholder: 'Select Doctor...'
            },
            parent: doctor_wrapper,
            render_input: true
        });

        // Room change event
        header.find('.room-select').on('change', () => {
            this.room = header.find('.room-select').val();
            if (this.room) {
                this.load_room_stock();
            }
        });
    }

    async load_rooms() {
        if (!this.branch) return;

        const result = await frappe.call({
            method: 'dental_clinic.api.material_usage.get_rooms_for_branch',
            args: { branch: this.branch }
        });

        const rooms = result.message || [];
        const select = this.page.main.find('.room-select');
        select.find('option:not(:first)').remove();
        rooms.forEach(room => {
            select.append(`<option value="${room.name}">${room.name}</option>`);
        });
    }

    render_record_form() {
        const container = this.page.main.find('.record-usage-container');
        container.html(`
            <div class="row">
                <div class="col-md-7">
                    <h6>Available Items in Room</h6>
                    <div class="room-stock-search mb-2">
                        <input type="text" class="form-control form-control-sm stock-search" placeholder="Search items...">
                    </div>
                    <div class="room-stock-table"></div>
                </div>
                <div class="col-md-5">
                    <h6>Usage Cart <span class="badge badge-primary cart-count">0</span></h6>
                    <div class="usage-cart"></div>
                    <div class="mt-3">
                        <textarea class="form-control usage-notes" rows="2" placeholder="Notes (optional)..."></textarea>
                    </div>
                    <div class="mt-3">
                        <button class="btn btn-primary btn-block submit-usage-btn" disabled>
                            <i class="fa fa-check"></i> Record Usage
                        </button>
                    </div>
                </div>
            </div>
        `);

        // Search event
        container.find('.stock-search').on('input', frappe.utils.debounce(() => {
            this.load_room_stock();
        }, 300));

        // Submit event
        container.find('.submit-usage-btn').on('click', () => this.submit_usage());
    }

    async load_room_stock() {
        if (!this.room) {
            this.page.main.find('.room-stock-table').html('<p class="text-muted">Select a room to see available stock.</p>');
            return;
        }

        const search = this.page.main.find('.stock-search').val();
        const table_container = this.page.main.find('.room-stock-table');
        table_container.html('<div class="text-center"><i class="fa fa-spinner fa-spin"></i></div>');

        try {
            const result = await frappe.call({
                method: 'dental_clinic.api.material_usage.get_room_stock',
                args: {
                    room_warehouse: this.room,
                    search: search || ''
                }
            });

            const items = result.message || [];
            if (items.length === 0) {
                table_container.html('<p class="text-muted">No items in stock for this room.</p>');
                return;
            }

            let html = '<table class="table table-sm table-bordered table-hover" style="font-size: 12px;">';
            html += '<thead><tr><th>Item</th><th class="text-right">Available</th><th>UOM</th><th></th></tr></thead><tbody>';

            items.forEach(item => {
                html += `
                    <tr>
                        <td><strong>${item.item_code}</strong><br><small class="text-muted">${item.item_name}</small></td>
                        <td class="text-right">${item.available_qty}</td>
                        <td>${item.uom}</td>
                        <td>
                            <button class="btn btn-xs btn-success add-to-cart-btn"
                                data-item-code="${item.item_code}"
                                data-item-name="${item.item_name}"
                                data-available="${item.available_qty}"
                                data-uom="${item.uom}">
                                <i class="fa fa-plus"></i>
                            </button>
                        </td>
                    </tr>
                `;
            });

            html += '</tbody></table>';
            table_container.html(html);

            // Bind add to cart
            table_container.find('.add-to-cart-btn').on('click', (e) => {
                const btn = $(e.currentTarget);
                this.add_to_cart(
                    btn.data('item-code'),
                    btn.data('item-name'),
                    btn.data('available'),
                    btn.data('uom')
                );
            });

        } catch (err) {
            table_container.html('<p class="text-danger">Error loading stock.</p>');
        }
    }

    add_to_cart(item_code, item_name, available, uom) {
        // Check if already in cart
        const existing = this.cart.find(c => c.item_code === item_code);
        if (existing) {
            if (existing.qty < available) {
                existing.qty += 1;
            } else {
                frappe.show_alert({ message: `Maximum available quantity reached for ${item_code}`, indicator: 'orange' });
                return;
            }
        } else {
            this.cart.push({
                item_code: item_code,
                item_name: item_name,
                qty: 1,
                available: available,
                uom: uom
            });
        }
        this.render_cart();
    }

    render_cart() {
        const container = this.page.main.find('.usage-cart');
        const count_badge = this.page.main.find('.cart-count');
        const submit_btn = this.page.main.find('.submit-usage-btn');

        count_badge.text(this.cart.length);
        submit_btn.prop('disabled', this.cart.length === 0);

        if (this.cart.length === 0) {
            container.html('<p class="text-muted">No items added yet. Click + to add items from the room stock.</p>');
            return;
        }

        let html = '<table class="table table-sm" style="font-size: 12px;">';
        html += '<thead><tr><th>Item</th><th>Qty</th><th></th></tr></thead><tbody>';

        this.cart.forEach((item, idx) => {
            html += `
                <tr>
                    <td>${item.item_code}<br><small class="text-muted">${item.item_name}</small></td>
                    <td>
                        <input type="number" class="form-control form-control-sm cart-qty-input"
                            data-idx="${idx}" value="${item.qty}" min="1" max="${item.available}"
                            style="width: 60px;">
                    </td>
                    <td>
                        <button class="btn btn-xs btn-danger remove-cart-btn" data-idx="${idx}">
                            <i class="fa fa-times"></i>
                        </button>
                    </td>
                </tr>
            `;
        });

        html += '</tbody></table>';
        container.html(html);

        // Bind events
        container.find('.cart-qty-input').on('change', (e) => {
            const idx = $(e.target).data('idx');
            const val = parseInt($(e.target).val());
            if (val > 0 && val <= this.cart[idx].available) {
                this.cart[idx].qty = val;
            } else {
                $(e.target).val(this.cart[idx].qty);
                frappe.show_alert({ message: 'Invalid quantity', indicator: 'orange' });
            }
        });

        container.find('.remove-cart-btn').on('click', (e) => {
            const idx = $(e.currentTarget).data('idx');
            this.cart.splice(idx, 1);
            this.render_cart();
        });
    }

    async submit_usage() {
        const px_file = this.page.main.find('.px-file-input').val().trim();
        const notes = this.page.main.find('.usage-notes').val().trim();
        const doctor = this.doctor_field ? this.doctor_field.get_value() : '';

        // Validation
        if (!px_file) {
            frappe.msgprint({
                title: 'PX File Required',
                message: 'PX File Number is mandatory for recording material usage.',
                indicator: 'red'
            });
            this.page.main.find('.px-file-input').focus();
            return;
        }

        if (!this.room) {
            frappe.msgprint('Please select a room first.');
            return;
        }

        if (this.cart.length === 0) {
            frappe.msgprint('Please add at least one item to the usage cart.');
            return;
        }

        // Validate all quantities are integers
        for (const item of this.cart) {
            if (item.qty !== Math.floor(item.qty) || item.qty <= 0) {
                frappe.msgprint(`Invalid quantity for ${item.item_code}. Must be a positive whole number.`);
                return;
            }
        }

        // Confirm
        frappe.confirm(
            `Record usage of ${this.cart.length} item(s) for PX File: <strong>${px_file}</strong>?`,
            async () => {
                frappe.show_progress('Recording usage...', 0, 100);

                try {
                    const result = await frappe.call({
                        method: 'dental_clinic.api.material_usage.record_usage',
                        args: {
                            room_warehouse: this.room,
                            items: JSON.stringify(this.cart.map(c => ({
                                item_code: c.item_code,
                                qty: c.qty
                            }))),
                            px_file_number: px_file,
                            doctor: doctor,
                            notes: notes
                        }
                    });

                    frappe.hide_progress();
                    frappe.show_alert({
                        message: result.message.message,
                        indicator: 'green'
                    }, 5);

                    // Clear cart and refresh
                    this.cart = [];
                    this.render_cart();
                    this.page.main.find('.px-file-input').val('');
                    this.page.main.find('.usage-notes').val('');
                    this.load_room_stock();

                } catch (err) {
                    frappe.hide_progress();
                    frappe.msgprint({
                        title: 'Error',
                        message: err.message || 'Failed to record usage.',
                        indicator: 'red'
                    });
                }
            }
        );
    }
}
