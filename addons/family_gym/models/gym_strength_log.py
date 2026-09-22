from odoo import api, fields, models


class GymStrengthLog(models.Model):
    """One exercise done on one day: the exercise plus all its sets (weight x reps)."""
    _name = 'gym.strength_log'
    _description = 'Exercise Session'
    _order = 'date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Who', default=lambda self: self.env.user, required=True, index=True)
    date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    workout_id = fields.Many2one(
        'gym.workout', string='Workout', ondelete='cascade',
        help='Set when the exercise was logged inside a calendar workout.')
    exercise_id = fields.Many2one('gym.exercise', string='Exercise', required=True, ondelete='restrict')
    set_ids = fields.One2many('gym.strength_set', 'log_id', string='Sets')
    notes = fields.Char()
    metric = fields.Selection(related='exercise_id.metric')
    summary = fields.Char(compute='_compute_summary', string='Sets done')
    # What the Exercises graph plots: the best weight of the session (its heaviest set), or the
    # best rep count for bodyweight exercises.
    chart_value = fields.Float(
        string='Best (kg or reps)', compute='_compute_chart_value', store=True,
        group_operator='max')

    @api.model_create_multi
    def create(self, vals_list):
        # Exercises typed into a workout inherit its person and day.
        for vals in vals_list:
            if vals.get('workout_id'):
                workout = self.env['gym.workout'].browse(vals['workout_id'])
                vals.setdefault('user_id', workout.user_id.id)
                vals.setdefault('date', fields.Date.to_string(workout.date))
        return super().create(vals_list)

    @api.depends('set_ids.weight', 'set_ids.reps', 'exercise_id.metric')
    def _compute_chart_value(self):
        for log in self:
            field_name = 'reps' if log.exercise_id.metric == 'reps' else 'weight'
            values = log.set_ids.mapped(field_name)
            log.chart_value = max(values) if values else 0

    @api.depends('set_ids.weight', 'set_ids.reps', 'set_ids.sequence', 'exercise_id.metric')
    def _compute_summary(self):
        for log in self:
            if log.exercise_id.metric == 'reps':
                parts = ['%d' % s.reps for s in log.set_ids]
            else:
                parts = ['%g×%d' % (s.weight, s.reps) for s in log.set_ids]
            log.summary = ' \u00b7 '.join(parts)
