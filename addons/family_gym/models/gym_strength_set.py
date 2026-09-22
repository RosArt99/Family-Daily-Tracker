from odoo import fields, models


class GymStrengthSet(models.Model):
    _name = 'gym.strength_set'
    _description = 'Exercise Set'
    _order = 'sequence, id'

    log_id = fields.Many2one(
        'gym.strength_log', string='Exercise', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    weight = fields.Float(string='Weight (kg)')
    reps = fields.Integer(string='Reps', default=10)

    _sql_constraints = [
        ('weight_positive', 'check(weight >= 0)', 'Weight cannot be negative.'),
        ('reps_positive', 'check(reps >= 0)', 'Reps cannot be negative.'),
    ]
