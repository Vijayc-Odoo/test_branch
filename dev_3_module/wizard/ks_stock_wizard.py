from odoo import fields, models

class StockDetailWizard(models.TransientModel):
    _name = 'stock.detail.wizard'
    _description = 'Stock Detail Filter'
    _rec_name = 'int_ref'

    company_id = fields.Many2one('res.company', string='Company')
    int_ref = fields.Char(string='Internal Reference')
    parent_category_ids = fields.Many2many(
        'product.category',
        'stock_detail_parent_categ_rel',
        'wizard_id',
        'category_id',
        string='Parent Categories'
    )

    child_category_ids = fields.Many2many(
        'product.category',
        'stock_detail_child_categ_rel',
        'wizard_id',
        'category_id',
        string='Child Categories',
        domain="[('parent_id', 'in', parent_category_ids)]"
    )

    filter_spec_ids = fields.One2many(
        'stock.detail.wizard.spec',
        'wizard_id',
        string='Filter Specifications'
    )

    product_line_ids = fields.One2many(
        'stock.detail.wizard.line',
        'wizard_id',
        string='Matching Products'
    )
    partner_id = fields.Many2one('res.partner', string='Vendor')
    product_stock = fields.Selection(
        [('positive_stock', 'Positive Stock'), ('negative_stock', 'Negative Stock'), ('zero_stock', 'Zero Stock')],
        string='Stock')
    active_state = fields.Selection([('all', 'All'), ('active', 'Active'), ('inactive', 'In Active')],
                                    string='Active State')
    running_item = fields.Selection([('running', 'Running'), ('not_running', 'Not Running')], string='Running Item')

    standard_price_id = fields.Many2one(
        'stock.detail.price',
        string="Cost Price", domain="[('wizard_id', '=', id)]"
    )

    price_option_ids = fields.One2many(
        'stock.detail.price',
        'wizard_id',
        string="Available Prices"
    )

    def _get_standard_price_selection(self):
        prices = set()
        for wizard in self:
            products = wizard.filtered_product_ids
            prices.update(products.mapped('standard_price'))

        return [(str(price), str(price)) for price in sorted(prices)]

    def action_filter_products(self):
        self.product_line_ids = [(5, 0, 0)]
        domain = [('type', 'in', ['consu', 'product'])]

        if self.active_state == 'active':
            domain.append(('active', '=', True))
        elif self.active_state == 'inactive':
            domain.append(('active', '=', False))
        else:
            self.active_state == 'all'
            domain.append(('active', '=', True))

        if self.int_ref:
            domain.append(('default_code', '=', self.int_ref))

        if self.company_id:
            domain.append(('company_id', '=', self.company_id))

        if self.parent_category_ids:
            domain.append(('categ_id', 'child_of', self.parent_category_ids.ids))

        if self.child_category_ids:
            domain.append(('categ_id', 'in', self.child_category_ids.ids))

        if self.partner_id:
            domain.append(('product_tmpl_id.seller_ids.partner_id', '=', self.partner_id.id))

        if self.filter_spec_ids:
            for spec in self.filter_spec_ids:
                matching_specs = self.env['product.specification.line'].search([
                    ('product_spec_id', '=', spec.product_spec_id.id),
                    ('product_spec_value_id', '=', spec.product_spec_value_id.id)
                ])
                domain.append(('product_tmpl_id', 'in', matching_specs.mapped('product_tmp_id').ids))

        products = self.env['product.product'].search(domain)

        if self.standard_price_id:
            products = products.filtered(
                lambda p: p.standard_price == self.standard_price_id.name
            )
        self.price_option_ids.unlink()

        unique_prices = sorted(set(products.mapped('standard_price')))

        price_lines = []
        for price in unique_prices:
            price_lines.append((0, 0, {
                'wizard_id': self.id,
                'name': price,
            }))

        self.write({'price_option_ids': price_lines})
        # self.write({'standard_price_id': price_lines})

        if self.product_stock == 'positive_stock':
            products = products.filtered(lambda p: p.qty_available > 0)

        elif self.product_stock == 'negative_stock':
            products = products.filtered(lambda p: p.virtual_available < 0)

        elif self.product_stock == 'zero_stock':
            products = products.filtered(lambda p: p.virtual_available == 0)

        if self.running_item == 'running':
            products = products.filtered(
                lambda p: p.orderpoint_ids and any(op.product_min_qty > p.virtual_available for op in p.orderpoint_ids)
            )
        elif self.running_item == 'not_running':
            products = products.filtered(
                lambda p: not p.orderpoint_ids or all(op.product_min_qty <= p.virtual_available for op in p.orderpoint_ids)
            )

        lines = []
        for product in products:
            orderpoints = product.orderpoint_ids
            if orderpoints:
                min_qty = sum(op.product_min_qty for op in orderpoints)
                max_qty = sum(op.product_max_qty for op in orderpoints)
            else:
                min_qty = 0
                max_qty = 0
            lines.append((0, 0, {
                'partner_id': product.product_tmpl_id.seller_ids[:1].partner_id.id,
                'product_id': product.id,
                'default_code': product.default_code,
                'categ_id': product.categ_id.id,
                'lst_price': product.lst_price,
                'qty_available': product.qty_available,
                'virtual_available': product.virtual_available,
                'item_cost': product.standard_price,
                'last_purchase_price': product.product_tmpl_id.last_purchase_price,
                'last_purchase_date': product.product_tmpl_id.last_purchase_date,
                'last_purchase_quantity': product.product_tmpl_id.last_purchase_quantity,
                'product_image' : product.product_tmpl_id.image_1920,
                'product_min_qty': min_qty,
                'product_max_qty': max_qty,
            }))

        self.write({'product_line_ids': lines})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.detail.wizard',
            'view_mode': 'form',
            'res_id': self.id,
        }

    def action_download_all_images(self):
        import io, base64, zipfile
        self.ensure_one()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            for line in self.product_line_ids:
                img_data = line.product_id.product_tmpl_id.image_1920
                if not img_data:
                    continue
                filename = f"{line.product_id.default_code or line.product_id.name}"
                zf.writestr(filename, base64.b64decode(img_data))

        zip_buffer.seek(0)
        zip_base64 = base64.b64encode(zip_buffer.read())

        attachment = self.env['ir.attachment'].create({
            'name': f'All_Product_Images_{self.id}.zip',
            'type': 'binary',
            'datas': zip_base64,
            'res_model': 'stock.detail.wizard',
            'res_id': self.id,
            'mimetype': 'application/zip',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class StockDetailWizardSpec(models.TransientModel):
    _name = 'stock.detail.wizard.spec'
    _description = 'Specification Filter Criteria'

    wizard_id = fields.Many2one('stock.detail.wizard')
    product_spec_id = fields.Many2one('product.specification', string="Specification", required=True)
    product_spec_value_id = fields.Many2one('product.specification.value', string="Value", required=True)


class StockDetailWizardLine(models.TransientModel):
    _name = 'stock.detail.wizard.line'
    _description = 'Stock Detail Result Line'

    wizard_id = fields.Many2one('stock.detail.wizard')
    product_id = fields.Many2one('product.product', string='Product')
    default_code = fields.Char(string='Description')
    categ_id = fields.Many2one('product.category', string='Category')
    lst_price = fields.Float(string='Amount')
    partner_id = fields.Many2one('res.partner', string='Vendor')
    qty_available = fields.Float(string='Product Stock')
    virtual_available = fields.Float(string='Negative Stock')
    item_cost = fields.Float(string='Item Cost')
    last_purchase_price = fields.Float(string="Last Purchase Price")
    last_purchase_date = fields.Datetime(string="Last Purchase Date")
    last_purchase_quantity = fields.Float(string="Last Purchase Quantity")
    standard_price = fields.Float(string="Standard Price")
    product_image = fields.Binary(string="Product Image")
    product_min_qty = fields.Float(string='Minimum Quantity')
    product_max_qty = fields.Float(string='Maximum Quantity')


class StockDetailPrice(models.TransientModel):
    _name = 'stock.detail.price'
    _description = 'Temporary Price Holder'

    wizard_id = fields.Many2one('stock.detail.wizard')
    name = fields.Float(string="Standard Price")
