from odoo import fields, models


class GymWeightLog(models.Model):
    _name = 'gym.weight_log'
    _description = 'Body Weight Log'
    _order = 'date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    weight = fields.Float(string='Weight (kg)', required=True, group_operator='avg')
    notes = fields.Char()
    source = fields.Selection(
        [('manual', 'Manual'), ('scale', 'Scale')], default='manual', required=True)
    # Exact time of the weigh-in as reported by the scale/Apple Health (UTC). Only set for
    # `scale` rows; it is what lets a repeated sync of the same weigh-in be recognised.
    measured_at = fields.Datetime(index=True, readonly=True)

    _sql_constraints = [
        ('weight_positive', 'check(weight > 0)', 'Weight must be positive.'),
    ]
