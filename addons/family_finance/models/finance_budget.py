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
    total_limit = fields.Monetary(string='All spending per month', currency_field='currency_id')

    _sql_constraints = [
        ('limits_not_negative',
         'check(groceries_limit >= 0 and housing_limit >= 0 and total_limit >= 0)',
         'A limit cannot be negative.'),
    ]

    @api.model
    def _get_budget(self):
        return self.search([], limit=1) or self.create({})

    @api.model
    def get_limits(self):
        budget = self._get_budget()
        return {
            'groceries': budget.groceries_limit,
            'housing': budget.housing_limit,
            'total': budget.total_limit,
        }

    @api.model
    def set_limits(self, groceries=0.0, housing=0.0, total=0.0):
        self._get_budget().write({
            'groceries_limit': max(groceries or 0.0, 0.0),
            'housing_limit': max(housing or 0.0, 0.0),
            'total_limit': max(total or 0.0, 0.0),
        })
        return self.get_limits()

    @api.model
    def action_open_limits(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Spending limits', 'res_model': self._name,
            'res_id': self._get_budget().id, 'views': [[False, 'form']], 'target': 'current',
        }
