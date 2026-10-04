from odoo import api, fields, models


class FinanceSaving(models.Model):
    _name = 'finance.saving'
    _description = 'Savings transfer'
    _order = 'date desc, id desc'

    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True,
        help='Whose income the money came from (or went back to).')
    kind = fields.Selection(
        [('deposit', 'To savings'), ('withdraw', 'Withdrawal')], default='deposit', required=True)
    # The money sits in USDT on Binance (counted as dollars), so a transfer is usually in USD
    # while the income it came from was hryvnias: each transfer keeps its own currency and the
    # rate to the company currency of the day.
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company currency')
    amount = fields.Monetary(currency_field='currency_id', required=True)
    rate = fields.Float(
        string='Rate', digits=(16, 6), default=1.0,
        help='How many units of the company currency 1 unit of this currency was worth that day '
             '(National Bank of Ukraine rate unless you changed it).')
    # +amount for a deposit, -amount for a withdrawal: sums of these fields are balances.
    signed_amount = fields.Monetary(
        currency_field='currency_id', compute='_compute_signed_amount', store=True)
    signed_base = fields.Monetary(
        string='In company currency', currency_field='company_currency_id',
        compute='_compute_signed_amount', store=True)
    is_foreign = fields.Boolean(compute='_compute_signed_amount', store=True)
    plan_id = fields.Many2one(
        'finance.plan', string='For plan', ondelete='set null', index=True,
        help='Leave empty for general savings.')
    notes = fields.Char()

    _sql_constraints = [
        ('amount_positive', 'check(amount > 0)', 'The amount must be positive.'),
    ]

    @api.depends('amount', 'kind', 'rate', 'currency_id', 'company_currency_id')
    def _compute_signed_amount(self):
        for rec in self:
            sign = 1 if rec.kind == 'deposit' else -1
            rec.is_foreign = rec.currency_id != rec.company_currency_id
            rec.signed_amount = sign * rec.amount
            rec.signed_base = sign * (rec.amount * rec.rate if rec.is_foreign else rec.amount)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self.env['finance.fx.rate']._ensure_rate(vals, self)
        return super().create(vals_list)

    def write(self, vals):
        if {'currency_id', 'date'} & set(vals) and 'rate' not in vals:
            for rec in self:
                merged = {'currency_id': rec.currency_id.id, 'date': rec.date, **vals}
                self.env['finance.fx.rate']._ensure_rate(merged, rec)
                vals = dict(vals, rate=merged['rate'])
        return super().write(vals)

    @api.onchange('currency_id', 'date')
    def _onchange_currency_rate(self):
        if self.currency_id:
            self.rate = self.env['finance.fx.rate'].get_rate(self.currency_id.id, self.date)['rate'] or 1.0

    def name_get(self):
        labels = dict(self._fields['kind'].selection)
        return [(rec.id, '%s - %s' % (labels[rec.kind], rec.date)) for rec in self]
