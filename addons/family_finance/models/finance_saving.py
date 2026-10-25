from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    # Money that only changes its place, not your income: a move between general savings and a
    # plan ('transfer'), or the plan being paid out of the savings ('payout'). Such entries never
    # count as "saved this month" and a payout is not part of what the plan has saved.
    move = fields.Selection(
        [('transfer', 'Moved between general savings and a plan'), ('payout', 'Paid out for the plan')],
        index=True)

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

    @api.constrains('kind', 'move', 'user_id', 'date', 'amount', 'rate', 'currency_id')
    def _check_within_available(self):
        """Money that has been spent cannot be put aside: a transfer from income may not be more
        than what is left of that person's income in the month (moves between general savings and
        a plan are exempt - the money is already saved)."""
        for rec in self:
            if rec.kind != 'deposit' or rec.move:
                continue
            start = rec.date.replace(day=1)
            left = self.env['finance.overview']._left_by_user(
                start, start + relativedelta(months=1), rec.ids).get(rec.user_id.id, 0.0)
            if rec.signed_base > max(left, 0.0) + 0.005:
                raise ValidationError(_(
                    '%(user)s can transfer at most %(left).2f %(currency)s from the income of %(month)s - '
                    'the rest has already been spent or put aside.',
                    user=rec.user_id.name, left=max(left, 0.0),
                    currency=rec.company_currency_id.name, month=start.strftime('%B %Y')))

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
