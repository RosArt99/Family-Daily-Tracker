from odoo import api, fields, models

from .gym_exercise import MUSCLE_GROUPS

WORKOUT_TYPES = [t for t in MUSCLE_GROUPS if t[0] not in ('core',)] + [('full_body', 'Full Body')]


class GymWorkout(models.Model):
    _name = 'gym.workout'
    _description = 'Workout'
    _order = 'date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    workout_type = fields.Selection(WORKOUT_TYPES, string='Type', default='chest', required=True)
    duration_min = fields.Integer(string='Duration (min)')
    notes = fields.Text(help='Free text, e.g. "pressed 120 kg on legs - new personal record".')
    strength_ids = fields.One2many('gym.strength_log', 'workout_id', string='Sets')

    @api.depends('user_id', 'workout_type')
    def _compute_display_name(self):
        # Type first: calendar chips are narrow on a phone, and the type is what you look for.
        labels = dict(self._fields['workout_type'].selection)
        for workout in self:
            first_name = (workout.user_id.name or '').split(' ')[0]
            workout.display_name = '%s - %s' % (labels.get(workout.workout_type, ''), first_name)

    def write(self, vals):
        res = super().write(vals)
        if 'date' in vals or 'user_id' in vals:
            for workout in self:
                workout.strength_ids.write({'date': workout.date, 'user_id': workout.user_id.id})
        return res
