from odoo import api, fields, models


class FinanceHousing(models.Model):
    _name = 'finance.housing'
    _inherit = ['finance.currency.mixin']
    _description = 'Housing Payment (rent & utilities)'
    _order = 'period desc, date desc, id desc'

    kind = fields.Selection(
        [('rent', 'Rent'), ('utilities', 'Utilities'), ('electricity', 'Electricity'),
         ('internet', 'Internet'), ('other', 'Other')],
        string='What', default='rent', required=True, index=True)
    date = fields.Date(string='Paid on', default=fields.Date.context_today, required=True, index=True)
    # The month the payment is FOR (rent for October is often paid on Sept 28), always stored as
    # the 1st of that month. The overview counts a payment in this month, not the pay date's.
    period = fields.Date(string='For month', required=True, index=True,
                         default=lambda self: fields.Date.context_today(self).replace(day=1))
    user_id = fields.Many2one(
        'res.users', string='Paid by', default=lambda self: self.env.user, required=True, index=True)
    amount = fields.Monetary(currency_field='currency_id', required=True)
    amount_base = fields.Monetary(
        string='In company currency', currency_field='company_currency_id',
        compute='_compute_amount_base', store=True)
    notes = fields.Char()
    photo_ids = fields.One2many('finance.photo', 'housing_id', string='Receipt photos')
    photo_count = fields.Integer(compute='_compute_photo_count')
    period_label = fields.Char(compute='_compute_period_label')

    _sql_constraints = [
        ('amount_positive', 'check(amount > 0)', 'The amount must be positive.'),
    ]

    @api.depends('period')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = rec.period.strftime('%B %Y') if rec.period else ''

    @api.depends('amount', 'rate', 'is_foreign')
    def _compute_amount_base(self):
        for rec in self:
            rec.amount_base = rec._to_base(rec.amount)

    @api.depends('photo_ids')
    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = len(rec.photo_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('period'):
                vals['period'] = fields.Date.to_date(vals['period']).replace(day=1)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('period'):
            vals = dict(vals, period=fields.Date.to_date(vals['period']).replace(day=1))
        return super().write(vals)

    def name_get(self):
        labels = dict(self._fields['kind'].selection)
        return [(rec.id, '%s - %s' % (labels[rec.kind], rec.period.strftime('%B %Y'))) for rec in self]
