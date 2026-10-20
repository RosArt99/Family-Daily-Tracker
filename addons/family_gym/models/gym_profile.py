import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

KCAL_PER_KG = 7700.0
# Daily energy use = resting metabolism x this, by how many days a week you train.
ACTIVITY_FACTOR = {0: 1.2, 1: 1.375, 2: 1.375, 3: 1.55, 4: 1.55, 5: 1.725, 6: 1.725, 7: 1.9}
# Without a finish date, aim for a sensible pace: share of body weight per week.
DEFAULT_LOSS_PACE = 0.005
DEFAULT_GAIN_PACE = 0.0025
MAX_PLAN_POINTS = 240


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
    # ---- weight plan (Weight screen): where you start, where you want to be, and when ----
    sex = fields.Selection([('male', 'Male'), ('female', 'Female')])
    age = fields.Integer(string='Age (years)')
    gym_days_per_week = fields.Integer(string='Gym visits per week', default=3)
    plan_start_date = fields.Date(string='Plan start')
    plan_start_weight = fields.Float(string='Starting weight (kg)')
    plan_target_date = fields.Date(string='Target date')

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)', 'Each person has exactly one profile.'),
        ('calorie_positive', 'check(calorie_goal >= 0)', 'The calorie goal cannot be negative.'),
        ('gym_days_range', 'check(gym_days_per_week >= 0 and gym_days_per_week <= 7)',
         'Gym visits per week must be between 0 and 7.'),
    ]

    @api.model
    def _get_profile(self):
        """The current user's profile, created with default goals the first time it is needed."""
        return self.search([('user_id', '=', self.env.uid)], limit=1) or self.create({})

    # ------------------------------------------------------------------ the weight plan
    # A plan is an estimate, not a prescription: resting metabolism (Mifflin-St Jeor) times an
    # activity factor from your gym visits gives what you burn a day; eating a steady amount
    # below/above that moves your weight by ~7700 kcal per kg. The amount is chosen so the
    # simulated weight reaches the target on the target date - and because a lighter body
    # burns less, the curve flattens out a little towards the end, as real ones do.

    @staticmethod
    def _tdee(weight, height, age, sex, days_per_week):
        bmr = 10.0 * weight + 6.25 * height - 5.0 * age + (5.0 if sex == 'male' else -161.0)
        return bmr * ACTIVITY_FACTOR[max(0, min(int(days_per_week or 0), 7))]

    @classmethod
    def _simulate(cls, start_weight, intake, days, height, age, sex, days_per_week):
        weight, weights = start_weight, [start_weight]
        for _day in range(days):
            weight += (intake - cls._tdee(weight, height, age, sex, days_per_week)) / KCAL_PER_KG
            weights.append(weight)
        return weights

    @api.model
    def _compute_plan(self, v):
        """The plan for `v` (sex, age, height_cm, start_weight, start_date, target_weight,
        target_date, days_per_week) as a dict; {'ready': False, 'missing': [...]} if something
        needed is not filled in yet."""
        today = fields.Date.context_today(self)
        missing = [
            label for key, label in (
                ('sex', _('sex')), ('age', _('age')), ('height_cm', _('height')),
                ('start_weight', _('current weight')), ('target_weight', _('target weight')))
            if not v.get(key)]
        if missing:
            return {'ready': False, 'missing': missing}
        sex, age, height = v['sex'], int(v['age']), float(v['height_cm'])
        w0, wt = float(v['start_weight']), float(v['target_weight'])
        days_pw = int(v.get('days_per_week') or 0)
        start = fields.Date.to_date(v.get('start_date')) or today
        if abs(wt - w0) < 0.05:
            return {'ready': False, 'missing': [], 'message': _('The target is the same as the current weight.')}
        goal = 'loss' if wt < w0 else 'gain'
        suggested = False
        target_date = fields.Date.to_date(v.get('target_date'))
        if target_date and target_date <= start:
            return {'ready': False, 'missing': [], 'message': _('The target date must be after the start.')}
        if not target_date:
            pace = DEFAULT_LOSS_PACE if goal == 'loss' else DEFAULT_GAIN_PACE
            weeks = abs(wt - w0) / (pace * w0)
            target_date = start + timedelta(days=max(7, int(math.ceil(weeks * 7))))
            suggested = True
        days = (target_date - start).days

        def end_weight(intake):
            return self._simulate(w0, intake, days, height, age, sex, days_pw)[-1]

        lo, hi = 800.0, 6000.0
        for _i in range(50):   # end weight rises with intake: bisect for the one that lands on target
            mid = (lo + hi) / 2.0
            if end_weight(mid) < wt:
                lo = mid
            else:
                hi = mid
        intake = max(800.0, min(6000.0, (lo + hi) / 2.0))
        weights = self._simulate(w0, intake, days, height, age, sex, days_pw)
        tdee0 = self._tdee(w0, height, age, sex, days_pw)
        weeks = days / 7.0
        weekly = (weights[-1] - w0) / weeks
        warnings = []
        if abs(weights[-1] - wt) > 0.3:
            warnings.append(_('That target date is not reachable at a safe intake: by then you would be about %.1f kg.') % weights[-1])
        pct = abs(weekly) / w0 * 100.0
        if goal == 'loss' and pct > 1.0:
            warnings.append(_('Losing more than 1%% of your weight a week (%.1f%%) risks losing muscle - consider a later date.') % pct)
        if goal == 'gain' and pct > 0.5:
            warnings.append(_('Gaining faster than 0.5%% a week (%.1f%%) will be mostly fat - consider a later date.') % pct)
        minimum = 1500 if sex == 'male' else 1200
        if goal == 'loss' and intake < minimum:
            warnings.append(_('%d kcal a day is below the usual minimum (%d) - consider a later date.') % (intake, minimum))
        step = max(1, int(math.ceil(len(weights) / float(MAX_PLAN_POINTS))))
        indexes = list(range(0, len(weights), step))
        if indexes[-1] != len(weights) - 1:
            indexes.append(len(weights) - 1)
        return {
            'ready': True,
            'goal': goal,
            'start_date': fields.Date.to_string(start),
            'target_date': fields.Date.to_string(target_date),
            'date_suggested': suggested,
            'start_weight': w0,
            'target_weight': wt,
            'days': days,
            'weeks': round(weeks, 1),
            'weekly_change': round(weekly, 2),
            'weekly_percent': round(pct, 2),
            'recommended_kcal': int(round(intake / 10.0) * 10),
            'tdee_kcal': int(round(tdee0 / 10.0) * 10),
            'daily_change_kcal': int(round((intake - tdee0) / 10.0) * 10),
            'warnings': warnings,
            'points': [[fields.Date.to_string(start + timedelta(days=i)), round(weights[i], 2)] for i in indexes],
        }

    def _plan_values(self):
        self.ensure_one()
        return {
            'sex': self.sex, 'age': self.age, 'height_cm': self.height_cm,
            'start_weight': self.plan_start_weight, 'start_date': self.plan_start_date,
            'target_weight': self.target_weight, 'target_date': self.plan_target_date,
            'days_per_week': self.gym_days_per_week,
        }

    @api.model
    def get_plan(self, user_id=None):
        """The saved plan of a person (default: the current user), or {'ready': False,...}."""
        profile = self.search([('user_id', '=', user_id or self.env.uid)], limit=1)
        if not profile:
            return {'ready': False, 'missing': []}
        return self._compute_plan(profile._plan_values())

    @api.model
    def get_plan_form(self):
        """Everything the plan dialog starts from: the saved values (current weight and start
        date default to your latest weigh-in/today) and the plan they give."""
        profile = self._get_profile()
        last = self.env['gym.weight_log'].search(
            [('user_id', '=', self.env.uid)], order='date desc, id desc', limit=1)
        today = fields.Date.context_today(self)
        values = {
            'sex': profile.sex or False, 'age': profile.age or 0, 'height_cm': profile.height_cm or 0,
            'start_weight': profile.plan_start_weight or (last.weight if last else 0.0),
            'start_date': fields.Date.to_string(profile.plan_start_date or today),
            'target_weight': profile.target_weight or 0.0,
            'target_date': fields.Date.to_string(profile.plan_target_date) if profile.plan_target_date else False,
            'days_per_week': profile.gym_days_per_week,
            'calorie_goal': profile.calorie_goal,
        }
        return {'values': values, 'plan': self._compute_plan(values), 'last_weight': last.weight if last else 0.0}

    @api.model
    def preview_plan(self, values):
        return self._compute_plan(values or {})

    @api.model
    def save_plan(self, values, set_calories=False):
        profile = self._get_profile()
        plan = self._compute_plan(values or {})
        if not plan.get('ready'):
            raise UserError(plan.get('message') or _('Fill in: %s.') % ', '.join(plan.get('missing') or []))
        vals = {
            'sex': values['sex'], 'age': int(values['age']), 'height_cm': int(float(values['height_cm'])),
            'plan_start_weight': float(values['start_weight']), 'plan_start_date': plan['start_date'],
            'target_weight': float(values['target_weight']), 'plan_target_date': plan['target_date'],
            'gym_days_per_week': int(values.get('days_per_week') or 0),
        }
        if set_calories:
            vals['calorie_goal'] = plan['recommended_kcal']
        profile.write(vals)
        return self._compute_plan(profile._plan_values())

    @api.model
    def clear_plan(self):
        self._get_profile().write({
            'plan_start_weight': 0.0, 'plan_start_date': False, 'plan_target_date': False, 'target_weight': 0.0})
        return True
