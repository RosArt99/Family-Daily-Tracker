from odoo import api, fields, models


class FinanceIncome(models.Model):
    _name = 'finance.income'
    _description = 'Income'
    _order = 'date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    # Salary arrives in hryvnias, the household spends zlotys: each entry keeps the currency it
    # was received in, the rate to the company currency, and the converted amount.
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company currency')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    amount = fields.Monetary(currency_field='currency_id', required=True)
    rate = fields.Float(
        string='Rate', digits=(16, 6), default=1.0,
        help='How many units of the company currency 1 unit of this currency was worth that day '
             '(National Bank of Ukraine rate unless you changed it).')
    amount_base = fields.Monetary(
        string='In company currency', currency_field='company_currency_id',
        compute='_compute_amount_base', store=True)
    is_foreign = fields.Boolean(compute='_compute_amount_base', store=True)
    source = fields.Selection(
        [('salary', 'Salary'), ('bonus', 'Bonus'), ('other', 'Other')],
        default='salary', required=True)
    notes = fields.Char()

    _sql_constraints = [
        ('amount_positive', 'check(amount > 0)', 'The amount must be positive.'),
    ]

    @api.depends('amount', 'rate', 'currency_id', 'company_currency_id')
    def _compute_amount_base(self):
        for rec in self:
            rec.is_foreign = rec.currency_id != rec.company_currency_id
            rec.amount_base = rec.amount * rec.rate if rec.is_foreign else rec.amount

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
        return [(inc.id, '%s - %s' % (inc.user_id.name, inc.date)) for inc in self]
