from odoo import fields, models


class FinanceStore(models.Model):
    _name = 'finance.store'
    _description = 'Store'
    _order = 'name'

    name = fields.Char(required=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'This store already exists.'),
    ]
