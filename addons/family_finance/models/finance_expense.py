from odoo import api, fields, models

# Every spending category the Expenses screens know. Groceries and Housing have their own models
# (a bill has a food/household split and a store, rent has a month it is for); the rest are plain
# expenses in `finance.expense`, told apart by `category`.
# key -> (label, Font Awesome icon)
EXPENSE_CATEGORIES = {
    'groceries': ('Groceries', 'fa-shopping-basket'),
    'housing': ('Housing', 'fa-home'),
    'subscriptions': ('Subscriptions', 'fa-repeat'),
    'restaurants': ('Restaurants', 'fa-cutlery'),
    'clothes': ('Clothes', 'fa-tag'),
    'car': ('Car', 'fa-car'),
    'other': ('Other', 'fa-ellipsis-h'),
}
PLAIN_CATEGORIES = ('subscriptions', 'restaurants', 'clothes', 'car', 'other')


class FinanceExpense(models.Model):
    _name = 'finance.expense'
    _description = 'Expense'
    _order = 'date desc, id desc'

    category = fields.Selection(
        [(key, EXPENSE_CATEGORIES[key][0]) for key in PLAIN_CATEGORIES],
        required=True, index=True, default='other')
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    title = fields.Char(string='What', help='Netflix, fuel, a restaurant name, a jacket...')
    user_id = fields.Many2one(
        'res.users', string='Paid by', default=lambda self: self.env.user, required=True, index=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    amount = fields.Monetary(currency_field='currency_id', required=True)
    notes = fields.Char()
    photo_ids = fields.One2many('finance.photo', 'expense_id', string='Receipt photos')
    photo_count = fields.Integer(compute='_compute_photo_count')

    _sql_constraints = [
        ('amount_positive', 'check(amount > 0)', 'The amount must be positive.'),
    ]

    @api.depends('photo_ids')
    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = len(rec.photo_ids)

    def name_get(self):
        labels = dict(self._fields['category'].selection)
        return [(rec.id, '%s - %s' % (rec.title or labels[rec.category], rec.date)) for rec in self]
