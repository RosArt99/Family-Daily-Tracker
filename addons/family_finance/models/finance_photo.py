from odoo import fields, models


class FinancePhoto(models.Model):
    _name = 'finance.photo'
    _description = 'Receipt / Payment Photo'
    _order = 'id'

    # A photo belongs to exactly one record: a grocery bill, a housing payment or an expense.
    bill_id = fields.Many2one('finance.bill', ondelete='cascade', index=True)
    housing_id = fields.Many2one('finance.housing', ondelete='cascade', index=True)
    expense_id = fields.Many2one('finance.expense', ondelete='cascade', index=True)
    # Big enough to read the small print on a receipt.
    image = fields.Image(string='Photo', max_width=1600, max_height=1600, required=True)
