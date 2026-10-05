from odoo import api, fields, models


class FinanceCurrencyMixin(models.AbstractModel):
    """Any money record that may be paid in a currency other than the company's (zloty): it keeps
    its own currency, the exchange rate of its day (National Bank of Ukraine unless edited) and -
    on the model itself - the converted amount, so statistics always add up in one currency.

    A model using this mixin defines its own `..._base` stored fields (they depend on which
    amount fields it has) from `rate` and `is_foreign`."""
    _name = 'finance.currency.mixin'
    _description = 'Money record with its own currency'

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company currency')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    rate = fields.Float(
        string='Rate', digits=(16, 6), default=1.0,
        help='How many units of the company currency 1 unit of this currency was worth that day '
             '(National Bank of Ukraine rate unless you changed it).')
    is_foreign = fields.Boolean(compute='_compute_is_foreign', store=True)

    @api.depends('currency_id', 'company_currency_id')
    def _compute_is_foreign(self):
        for rec in self:
            rec.is_foreign = rec.currency_id != rec.company_currency_id

    def _to_base(self, amount):
        """`amount` (in this record's currency) converted to the company currency."""
        self.ensure_one()
        return amount * self.rate if self.is_foreign else amount

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
