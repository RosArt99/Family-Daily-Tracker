import pytz

from odoo import api, fields, models

from .gym_exercise import MUSCLE_GROUPS

WORKOUT_TYPES = [t for t in MUSCLE_GROUPS if t[0] not in ('core',)] + [
    ('upper', 'Upper'), ('full_body', 'Full Body')]


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
    # check_in is filled in by the club Wi-Fi automation (see wifi_event). check_out / duration_min
    # only hold old visits from when "leave" was tracked; nothing writes them any more.
    # Several kinds of training in one day (Legs + Cardio): keys of WORKOUT_TYPES, comma-separated.
    # `workout_type` keeps the first of them (and 'other' when there is none) for the old views.
    workout_types = fields.Char(string='Types', help='e.g. "legs,cardio"')
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

    @api.model
    def wifi_event(self, event, moment):
        """Handle "joined the club Wi-Fi" at `moment` (naive UTC) for the current user: the first
        join of a day starts the visit, later ones (the signal flaps on a weak connection) change
        nothing. "leave" is ignored: the Wi-Fi drops by itself while the phone lies on the gym
        floor, so it says nothing about leaving, and the visit length is no longer tracked."""
        if event != 'join':
            return {'status': 'ignored', 'reason': 'only "join" is used'}
        tz = pytz.timezone(self.env.user.tz or 'UTC')
        day = pytz.utc.localize(moment).astimezone(tz).date()
        workout = self.search([('user_id', '=', self.env.uid), ('date', '=', day)], limit=1)
        if not workout:
            workout = self.create({
                'date': day, 'workout_type': 'other', 'source': 'wifi', 'check_in': moment})
            return {'status': 'created', 'id': workout.id, 'date': fields.Date.to_string(day)}
        if not workout.check_in:
            workout.check_in = moment
        return {'status': 'exists', 'id': workout.id, 'date': fields.Date.to_string(day)}

    def day_types(self):
        """The kinds of training of this workout as a list of keys: the multi-select field, or -
        for workouts made before it existed - the single `workout_type`."""
        self.ensure_one()
        keys = [key for key in (self.workout_types or '').split(',') if key]
        if not keys and self.workout_type and self.workout_type != 'other':
            keys = [self.workout_type]
        # Chest / shoulders / arms are all "Upper" now; fold old values into it, without repeats.
        folded = []
        for key in keys:
            key = 'upper' if key in ('chest', 'shoulders', 'arms') else key
            if key not in folded:
                folded.append(key)
        return folded

    @api.model
    def toggle_type(self, day, workout_type):
        """Tap a type on the Exercises screen: add it to that day's kinds of training, or take it
        off again. Choosing one marks the day as a gym visit; removing the last keeps the visit."""
        target = fields.Date.to_date(day) or fields.Date.context_today(self)
        if workout_type not in dict(self._fields['workout_type'].selection) or workout_type == 'other':
            return []
        workout = self.search([('user_id', '=', self.env.uid), ('date', '=', target)], limit=1)
        keys = workout.day_types() if workout else []
        keys = [k for k in keys if k != workout_type] if workout_type in keys else keys + [workout_type]
        vals = {'workout_types': ','.join(keys), 'workout_type': keys[0] if keys else 'other'}
        if workout:
            workout.write(vals)
        else:
            self.create(dict(vals, date=target))
        return keys
