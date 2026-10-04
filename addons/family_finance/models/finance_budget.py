from odoo import api, fields, models


class FinanceBudget(models.Model):
    _name = 'finance.budget'
    _description = 'Monthly spending limits'

    # One shared record for the household (like the calorie goals in Gym & Fit, but not per
    # person: the groceries and the rent come out of the same pocket). 0 = no limit.
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    groceries_limit = fields.Monetary(string='Groceries per month', currency_field='currency_id')
    housing_limit = fields.Monetary(string='Housing per month', currency_field='currency_id')
    subscriptions_limit = fields.Monetary(string='Subscriptions per month', currency_field='currency_id')
    restaurants_limit = fields.Monetary(string='Restaurants per month', currency_field='currency_id')
    clothes_limit = fields.Monetary(string='Clothes per month', currency_field='currency_id')
    car_limit = fields.Monetary(string='Car per month', currency_field='currency_id')
    other_limit = fields.Monetary(string='Other per month', currency_field='currency_id')
    total_limit = fields.Monetary(string='All spending per month', currency_field='currency_id')

    _sql_constraints = [
        ('limits_not_negative',
         'check(groceries_limit >= 0 and housing_limit >= 0 and subscriptions_limit >= 0 '
         'and restaurants_limit >= 0 and clothes_limit >= 0 and car_limit >= 0 '
         'and other_limit >= 0 and total_limit >= 0)',
         'A limit cannot be negative.'),
    ]

    @api.model
    def _get_budget(self):
        return self.search([], limit=1) or self.create({})

    LIMIT_KEYS = ('groceries', 'housing', 'subscriptions', 'restaurants', 'clothes', 'car', 'other', 'total')

    @api.model
    def get_limits(self):
        budget = self._get_budget()
        return {key: budget['%s_limit' % key] for key in self.LIMIT_KEYS}

    @api.model
    def set_limits(self, limits):
        """`limits` maps a key (see LIMIT_KEYS) to its monthly amount; missing keys become 0."""
        self._get_budget().write({
            '%s_limit' % key: max((limits or {}).get(key) or 0.0, 0.0) for key in self.LIMIT_KEYS})
        return self.get_limits()

    @api.model
    def action_open_limits(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Spending limits', 'res_model': self._name,
            'res_id': self._get_budget().id, 'views': [[False, 'form']], 'target': 'current',
        }
