from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FinanceBill(models.Model):
    _name = 'finance.bill'
    _inherit = ['finance.currency.mixin']
    _description = 'Grocery Bill'
    _order = 'date desc, id desc'

    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    store_id = fields.Many2one('finance.store', string='Store', index=True,
                               help='Where it was bought (Biedronka, Lidl, ...).')
    user_id = fields.Many2one(
        'res.users', string='Paid by', default=lambda self: self.env.user, required=True, index=True)
    # Only the bill's total and the household part are typed in - no per-product prices. Food is
    # whatever is left, so the three numbers can never disagree.
    total_amount = fields.Monetary(string='Bill total', currency_field='currency_id', required=True)
    household_amount = fields.Monetary(
        string='Household (non-food)', currency_field='currency_id', default=0.0,
        help='The part of the bill spent on household chemicals, toilet paper and other non-food items.')
    food_amount = fields.Monetary(
        string='Food', currency_field='currency_id', compute='_compute_food_amount', store=True)
    # The same three amounts converted to the company currency (what the statistics add up).
    total_base = fields.Monetary(
        string='Total (company currency)', currency_field='company_currency_id',
        compute='_compute_bases', store=True)
    household_base = fields.Monetary(
        string='Household (company currency)', currency_field='company_currency_id',
        compute='_compute_bases', store=True)
    food_base = fields.Monetary(
        string='Food (company currency)', currency_field='company_currency_id',
        compute='_compute_bases', store=True)
    notes = fields.Char()
    photo_ids = fields.One2many('finance.photo', 'bill_id', string='Receipt photos')
    photo_count = fields.Integer(compute='_compute_photo_count')

    _sql_constraints = [
        ('total_not_negative', 'check(total_amount >= 0)', 'The bill total cannot be negative.'),
        ('household_not_negative', 'check(household_amount >= 0)', 'The household part cannot be negative.'),
    ]

    @api.depends('total_amount', 'household_amount')
    def _compute_food_amount(self):
        for bill in self:
            bill.food_amount = bill.total_amount - bill.household_amount

    @api.depends('total_amount', 'household_amount', 'food_amount', 'rate', 'is_foreign')
    def _compute_bases(self):
        for bill in self:
            bill.total_base = bill._to_base(bill.total_amount)
            bill.household_base = bill._to_base(bill.household_amount)
            bill.food_base = bill._to_base(bill.food_amount)

    @api.depends('photo_ids')
    def _compute_photo_count(self):
        for bill in self:
            bill.photo_count = len(bill.photo_ids)

    @api.constrains('total_amount', 'household_amount')
    def _check_household_within_total(self):
        for bill in self:
            if bill.household_amount > bill.total_amount:
                raise ValidationError(
                    'The household part (%s) cannot be more than the bill total (%s).'
                    % (bill.household_amount, bill.total_amount))

    def name_get(self):
        return [(bill.id, '%s - %s' % (bill.store_id.name or 'Bill', bill.date)) for bill in self]
