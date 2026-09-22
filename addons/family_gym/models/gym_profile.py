from odoo import api, fields, models


class GymProfile(models.Model):
    _name = 'gym.profile'
    _description = 'Fitness Profile & Daily Goals'
    _order = 'user_id'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True,
        ondelete='cascade', index=True)
    calorie_goal = fields.Integer(string='Calories (kcal/day)', default=2000)
    protein_goal = fields.Integer(string='Protein (g/day)', default=100)
    carbs_goal = fields.Integer(string='Carbs (g/day)', default=250)
    fat_goal = fields.Integer(string='Fat (g/day)', default=70)
    height_cm = fields.Integer(string='Height (cm)')
    target_weight = fields.Float(string='Target weight (kg)')

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)', 'Each person has exactly one profile.'),
        ('calorie_positive', 'check(calorie_goal >= 0)', 'The calorie goal cannot be negative.'),
    ]

    @api.model
    def _get_profile(self):
        """The current user's profile, created with default goals the first time it is needed."""
        return self.search([('user_id', '=', self.env.uid)], limit=1) or self.create({})
