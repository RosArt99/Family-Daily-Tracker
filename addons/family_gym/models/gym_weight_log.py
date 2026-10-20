from datetime import timedelta

from odoo import api, fields, models


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

    # ------------------------------------------------------------------ Weight screen data

    @api.model
    def get_weight_screen(self, date_from=False, date_to=False):
        """Everything the Weight screen draws, in one call: my weigh-ins and everyone else's in
        the chosen period, my last measurement and BMI, and my weight plan."""
        today = fields.Date.context_today(self)
        end = fields.Date.to_date(date_to) or today
        start = fields.Date.to_date(date_from) or end - timedelta(days=29)
        if start > end:
            start, end = end, start
        me = self.env.user
        in_range = [('date', '>=', start), ('date', '<=', end)]

        def points(user):
            rows = self.search([('user_id', '=', user.id)] + in_range, order='date, id')
            by_day = {}
            for row in rows:        # one point a day (the last weigh-in of the day)
                by_day[row.date] = row.weight
            return [[fields.Date.to_string(day), round(weight, 1)] for day, weight in sorted(by_day.items())]

        mine = points(me)
        weights = [weight for _day, weight in mine]
        others = []
        for user in self.search([('user_id', '!=', me.id)]).mapped('user_id'):
            pts = points(user)
            others.append({'id': user.id, 'name': user.name, 'points': pts})

        last = self.search([('user_id', '=', me.id)], order='date desc, id desc', limit=2)
        profile = self.env['gym.profile'].search([('user_id', '=', me.id)], limit=1)
        height = profile.height_cm
        bmi = round(last[0].weight / ((height / 100.0) ** 2), 1) if last and height else None
        first_any = self.search([], order='date', limit=1)
        plan = self.env['gym.profile'].get_plan()
        return {
            'me': {'id': me.id, 'name': me.name},
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'today': fields.Date.to_string(today),
            'first_date': fields.Date.to_string(first_any.date) if first_any else fields.Date.to_string(today),
            'mine': mine,
            'others': others,
            'stats': {
                'min': min(weights) if weights else None,
                'max': max(weights) if weights else None,
                'avg': round(sum(weights) / len(weights), 2) if weights else None,
            },
            'last': {
                'weight': last[0].weight, 'date': fields.Date.to_string(last[0].date),
                'delta': round(last[0].weight - last[1].weight, 1) if len(last) > 1 else None,
            } if last else None,
            'height_cm': height,
            'bmi': bmi,
            'plan': plan,
        }
