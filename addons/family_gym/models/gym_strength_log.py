import calendar as pycalendar
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# What a calendar square says about a day: the kind of training, from the muscle group of the
# exercises done (or the type picked on an old workout). Chest/shoulders/arms are all "Upper".
TAG_BY_GROUP = {
    'legs': 'Legs', 'back': 'Back', 'cardio': 'Cardio', 'core': 'Core',
    'chest': 'Upper', 'shoulders': 'Upper', 'arms': 'Upper', 'upper': 'Upper', 'full_body': 'Full body',
}


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

    # ------------------------------------------------------------------ Exercises screen API

    @api.model
    def _day_tags(self, logs, workouts):
        tags = []
        for log in logs:
            tag = TAG_BY_GROUP.get(log.exercise_id.muscle_group)
            if tag and tag not in tags:
                tags.append(tag)
        for workout in workouts:
            for key in workout.day_types():
                tag = TAG_BY_GROUP.get(key)
                if tag and tag not in tags:
                    tags.append(tag)
        return tags

    def _entry_dict(self):
        self.ensure_one()
        return {
            'id': self.id,
            'exercise_id': self.exercise_id.id,
            'name': self.exercise_id.name,
            'metric': self.exercise_id.metric,
            'muscle': TAG_BY_GROUP.get(self.exercise_id.muscle_group) or '',
            'summary': self.summary or '',
            'best': self.chart_value,
            'notes': self.notes or '',
            'sets': [{'weight': st.weight, 'reps': st.reps} for st in self.set_ids],
        }

    @api.model
    def get_exercise_screen(self, day=None, year=None, month=None):
        """One day of training (the selected day's exercises and gym visit), the month's
        calendar squares and the exercise list - everything the Exercises screen draws."""
        today = fields.Date.context_today(self)
        selected = fields.Date.to_date(day) or today
        first = date(int(year or selected.year), int(month or selected.month), 1)
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        uid = self.env.uid
        Workout = self.env['gym.workout']

        logs_month = self.search([('user_id', '=', uid), ('date', '>=', first), ('date', '<', nxt)])
        works_month = Workout.search([('user_id', '=', uid), ('date', '>=', first), ('date', '<', nxt)])
        days = {}
        for current in sorted(set(logs_month.mapped('date')) | set(works_month.mapped('date'))):
            day_logs = logs_month.filtered(lambda l, d=current: l.date == d)
            day_works = works_month.filtered(lambda w, d=current: w.date == d)
            days[fields.Date.to_string(current)] = {'tags': self._day_tags(day_logs, day_works)}

        entries = self.search([('user_id', '=', uid), ('date', '=', selected)], order='id')
        workout = Workout.search([('user_id', '=', uid), ('date', '=', selected)], limit=1)
        recent = self.search([('user_id', '=', uid)], order='date desc, id desc', limit=80)
        recent_ids = []
        for log in recent:
            if log.exercise_id.id not in recent_ids:
                recent_ids.append(log.exercise_id.id)
        return {
            'today': fields.Date.to_string(today),
            'day': fields.Date.to_string(selected),
            'year': first.year,
            'month': first.month,
            'month_days': pycalendar.monthrange(first.year, first.month)[1],
            'first_weekday': first.weekday(),      # Monday = 0
            'days': days,
            'visit': bool(entries or workout),
            'has_workout': bool(workout),
            'workout_types': workout.day_types() if workout else [],
            'visit_minutes': workout.duration_min if workout else 0,
            'entries': [entry._entry_dict() for entry in entries],
            'exercises': [
                {'id': ex.id, 'name': ex.name, 'metric': ex.metric, 'muscle_group': ex.muscle_group}
                for ex in self.env['gym.exercise'].search([], order='name')],
            'recent_ids': recent_ids,
        }

    @api.model
    def get_last_session(self, exercise_id):
        """"Last time: 100x12 - 120x8": a nudge for what to lift today."""
        last = self.search(
            [('user_id', '=', self.env.uid), ('exercise_id', '=', exercise_id)],
            order='date desc, id desc', limit=1)
        return {'date': fields.Date.to_string(last.date), 'summary': last.summary} if last else False

    @api.model
    def save_exercise(self, values):
        """Create (no `id`) or update one exercise session of a day. A new exercise typed by
        name is created on the spot."""
        Exercise = self.env['gym.exercise']
        exercise_id = values.get('exercise_id')
        if not exercise_id:
            name = (values.get('new_name') or '').strip()
            if not name:
                raise UserError(_('Choose or type an exercise.'))
            exercise = Exercise.search([('name', '=ilike', name)], limit=1) or Exercise.create({
                'name': name, 'metric': values.get('metric') or 'strength',
                'muscle_group': values.get('muscle_group') or 'other'})
            exercise_id = exercise.id
        exercise = Exercise.browse(exercise_id)
        sets = [
            (0, 0, {
                'sequence': 10 * (index + 1),
                'weight': 0.0 if exercise.metric == 'reps' else float(item.get('weight') or 0),
                'reps': int(item.get('reps') or 0),
            })
            for index, item in enumerate(values.get('sets') or [])
            if float(item.get('weight') or 0) > 0 or int(item.get('reps') or 0) > 0]
        if not sets:
            raise UserError(_('Add at least one set.'))
        vals = {'exercise_id': exercise_id, 'notes': (values.get('notes') or '').strip() or False}
        if values.get('id'):
            record = self.browse(values['id'])
            record.write(dict(vals, set_ids=[(5, 0, 0)] + sets))
        else:
            day = fields.Date.to_date(values.get('date')) or fields.Date.context_today(self)
            workout = self.env['gym.workout'].search(
                [('user_id', '=', self.env.uid), ('date', '=', day)], limit=1)
            record = self.create(dict(
                vals, date=day, set_ids=sets, workout_id=workout.id if workout else False))
        return record.id

    @api.model
    def delete_exercise(self, record_id):
        self.browse(record_id).unlink()
        return True

    @api.model
    def get_exercise_progress(self, exercise_id, date_from=False, date_to=False):
        """The best weight (or reps) per day of one exercise, mine and everyone else's."""
        today = fields.Date.context_today(self)
        end = fields.Date.to_date(date_to) or today
        start = fields.Date.to_date(date_from) or end - timedelta(days=89)
        if start > end:
            start, end = end, start
        exercise = self.env['gym.exercise'].browse(exercise_id).exists()

        def points(user):
            logs = self.search([
                ('user_id', '=', user.id), ('exercise_id', '=', exercise_id),
                ('date', '>=', start), ('date', '<=', end)], order='date, id')
            best = {}
            for log in logs:
                best[log.date] = max(best.get(log.date, 0), log.chart_value)
            return [[fields.Date.to_string(day), value] for day, value in sorted(best.items()) if value > 0]

        me = self.env.user
        mine = points(me)
        values = [value for _day, value in mine]
        others = []
        for user in self.search([('exercise_id', '=', exercise_id), ('user_id', '!=', me.id)]).mapped('user_id'):
            pts = points(user)
            others.append({'id': user.id, 'name': user.name, 'points': pts})
        first_any = self.search([('user_id', '=', me.id), ('exercise_id', '=', exercise_id)], order='date', limit=1)
        return {
            'exercise': {'id': exercise.id, 'name': exercise.name, 'metric': exercise.metric} if exercise else False,
            'date_from': fields.Date.to_string(start), 'date_to': fields.Date.to_string(end),
            'today': fields.Date.to_string(today),
            'first_date': fields.Date.to_string(first_any.date) if first_any else fields.Date.to_string(start),
            'mine': mine, 'others': others,
            'stats': {
                'first': values[0] if values else None, 'last': values[-1] if values else None,
                'best': max(values) if values else None,
            },
        }
