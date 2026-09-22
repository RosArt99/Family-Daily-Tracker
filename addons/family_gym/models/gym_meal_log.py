from odoo import api, fields, models

MEAL_TYPES = [
    ('breakfast', 'Breakfast'),
    ('lunch', 'Lunch'),
    ('dinner', 'Dinner'),
    ('snack', 'Snacks/Other'),
]


class GymMealLog(models.Model):
    _name = 'gym.meal_log'
    _description = 'Meal Log'
    _order = 'date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    meal_type = fields.Selection(MEAL_TYPES, string='Meal', default='lunch', required=True)
    # Pick a product from the pantry (Groceries) to get its nutrition automatically, or leave it
    # empty and type the name/values by hand for something that isn't in the catalog.
    product_id = fields.Many2one('groceries.product', string='Food', ondelete='set null')
    name = fields.Char(compute='_compute_name', store=True, readonly=False)
    quantity_g = fields.Float(string='Amount (g/ml)', default=100.0)
    calories = fields.Float(string='kcal', compute='_compute_nutrition', store=True, readonly=False)
    proteins = fields.Float(string='Protein (g)', compute='_compute_nutrition', store=True, readonly=False)
    carbs = fields.Float(string='Carbs (g)', compute='_compute_nutrition', store=True, readonly=False)
    fat = fields.Float(string='Fat (g)', compute='_compute_nutrition', store=True, readonly=False)

    _sql_constraints = [
        ('quantity_positive', 'check(quantity_g >= 0)', 'Amount cannot be negative.'),
    ]

    @api.depends('product_id')
    def _compute_name(self):
        for meal in self:
            if meal.product_id:
                meal.name = meal.product_id.name

    @api.depends('product_id', 'quantity_g')
    def _compute_nutrition(self):
        # Values are only (re)computed from a product; without one they stay as typed.
        for meal in self:
            product = meal.product_id
            if product:
                factor = meal.quantity_g / 100.0
                meal.calories = round(product.energy_kcal_100g * factor, 1)
                meal.proteins = round(product.proteins_100g * factor, 1)
                meal.carbs = round(product.carbohydrates_100g * factor, 1)
                meal.fat = round(product.fat_100g * factor, 1)

    @api.model
    def get_diary(self, date=None):
        """Everything the Meals diary screen shows for ONE day of the current user:
        goals, totals and the entries grouped into Breakfast/Lunch/Dinner/Snacks."""
        day = fields.Date.to_date(date) if date else fields.Date.context_today(self)
        profile = self.env['gym.profile']._get_profile()
        entries = self.search([('user_id', '=', self.env.uid), ('date', '=', day)], order='id')

        def totals(records):
            return {
                'calories': round(sum(records.mapped('calories'))),
                'protein': round(sum(records.mapped('proteins'))),
                'carbs': round(sum(records.mapped('carbs'))),
                'fat': round(sum(records.mapped('fat'))),
            }

        sections = []
        for key, label in MEAL_TYPES:
            items = entries.filtered(lambda e, key=key: e.meal_type == key)
            sections.append({
                'key': key,
                'label': label,
                'calories': round(sum(items.mapped('calories'))),
                'entries': [{
                    'id': e.id,
                    'name': e.name or e.product_id.name or '',
                    'amount': round(e.quantity_g),
                    'calories': round(e.calories),
                } for e in items],
            })
        eaten = totals(entries)
        return {
            'date': fields.Date.to_string(day),
            'is_today': day == fields.Date.context_today(self),
            'profile_id': profile.id,
            'goals': {
                'calories': profile.calorie_goal,
                'protein': profile.protein_goal,
                'carbs': profile.carbs_goal,
                'fat': profile.fat_goal,
            },
            'totals': eaten,
            'remaining': profile.calorie_goal - eaten['calories'],
            'sections': sections,
        }
