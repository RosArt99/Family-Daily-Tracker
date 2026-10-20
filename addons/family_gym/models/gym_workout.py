import pytz

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
    # Filled in by the club Wi-Fi automation (see wifi_event): when you joined/left its network.
    source = fields.Selection([('manual', 'Manual'), ('wifi', 'Club Wi-Fi')], default='manual', required=True)
    check_in = fields.Datetime()
    check_out = fields.Datetime()
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

    @api.model
    def toggle_visit(self, day=None):
        """Mark/unmark "I was at the gym" for a day (the current user). A day with exercises
        logged counts as a visit by itself, so this only ever adds/removes a bare check-in."""
        target = fields.Date.to_date(day) or fields.Date.context_today(self)
        existing = self.search([('user_id', '=', self.env.uid), ('date', '=', target)])
        if existing:
            if self.env['gym.strength_log'].search_count(
                    [('user_id', '=', self.env.uid), ('date', '=', target)]):
                return True        # exercises are logged: it is a visit whatever happens here
            existing.unlink()
            return False
        self.create({'date': target, 'workout_type': 'other'})
        return True

    # Joining the club Wi-Fi also happens just walking past it in the mall corridor; a stay shorter
    # than this does not count (and is dropped if nothing was logged meanwhile).
    MIN_VISIT_MINUTES = 15

    @api.model
    def wifi_event(self, event, moment):
        """Handle "joined / left the club Wi-Fi" at `moment` (naive UTC) for the current user.
        The first join of a day starts the visit; each leave updates its length; a stay under
        MIN_VISIT_MINUTES with no exercises logged is removed again."""
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        day = pytz.utc.localize(moment).astimezone(tz).date()
        workout = self.search([('user_id', '=', self.env.uid), ('date', '=', day)], limit=1)
        if event == 'join':
            if not workout:
                workout = self.create({
                    'date': day, 'workout_type': 'other', 'source': 'wifi', 'check_in': moment})
                return {'status': 'created', 'id': workout.id, 'date': fields.Date.to_string(day)}
            if not workout.check_in:
                workout.check_in = moment
            return {'status': 'exists', 'id': workout.id, 'date': fields.Date.to_string(day)}
        # leave
        if not workout or not workout.check_in:
            return {'status': 'ignored', 'reason': 'no visit started today'}
        minutes = max(int((moment - workout.check_in).total_seconds() // 60), 0)
        has_exercises = self.env['gym.strength_log'].search_count(
            [('user_id', '=', self.env.uid), ('date', '=', day)])
        if workout.source == 'wifi' and minutes < self.MIN_VISIT_MINUTES and not has_exercises:
            workout.unlink()
            return {'status': 'dropped', 'minutes': minutes}
        workout.write({'check_out': moment, 'duration_min': minutes})
        return {'status': 'updated', 'id': workout.id, 'minutes': minutes}
