from odoo import api, fields, models


class GroceriesStockEntry(models.Model):
    _name = 'groceries.stock_entry'
    _inherit = ['mail.thread']
    _description = 'Groceries Stock Entry'
    _order = 'purchase_date desc, id desc'

    product_id = fields.Many2one(
        'groceries.product', string='Product', required=True, ondelete='restrict', tracking=True)
    user_id = fields.Many2one(
        'res.users', string='Added By', default=lambda self: self.env.user, required=True)

    # Lifecycle: scanned as "need to buy" -> scanned in store at checkout -> scanned
    # before throwing the empty pack away (or manually marked as finished).
    state = fields.Selection([
        ('to_buy', 'To Buy'),
        ('in_stock', 'In Stock'),
        ('consumed', 'Consumed / Discarded'),
    ], string='Status', default='to_buy', required=True, index=True, tracking=True,
        group_expand='_read_group_state')

    quantity = fields.Float(string='Quantity', default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    product_image = fields.Image(related='product_id.image', string='Photo', readonly=True)

    purchase_date = fields.Date(string='Purchase Date')
    expiration_date = fields.Date(string='Expiration Date')
    consumed_date = fields.Date(string='Consumed / Discarded Date')

    @api.model
    def _read_group_state(self, states, domain, order):
        # Kanban columns otherwise come out alphabetically by value (consumed, in_stock,
        # to_buy) and empty ones are hidden; always show the whole lifecycle left to right.
        return [key for key, _label in self._fields['state'].selection]

    def write(self, vals):
        res = super().write(vals)
        # Dragging a kanban card only writes `state`; keep the dates the buttons/scanner set.
        today = fields.Date.context_today(self)
        if vals.get('state') == 'in_stock':
            self.filtered(lambda e: not e.purchase_date).purchase_date = today
        elif vals.get('state') == 'consumed':
            self.filtered(lambda e: not e.consumed_date).consumed_date = today
        return res

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for entry in self:
            if entry.product_id.default_uom_id:
                entry.uom_id = entry.product_id.default_uom_id

    def action_open_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.product_id.display_name,
            'res_model': 'groceries.product',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_purchased(self):
        self.write({'state': 'in_stock', 'purchase_date': fields.Date.context_today(self)})

    def action_mark_consumed(self):
        self.write({'state': 'consumed', 'consumed_date': fields.Date.context_today(self)})
