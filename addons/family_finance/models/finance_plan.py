import math
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# What the Plans screen offers; "cancelled" only exists for old records.
PLAN_STATES = ('planning', 'saving', 'done')


class FinancePlan(models.Model):
    _name = 'finance.plan'
    _description = 'Travel / Big Purchase Plan'
    _order = 'state_order, target_date, id'

    name = fields.Char(string='Plan', required=True)
    kind = fields.Selection(
        [('travel', 'Travel'), ('purchase', 'Big purchase')], default='travel', required=True)
    state = fields.Selection(
        [('planning', 'Planning'), ('saving', 'Saving'), ('done', 'Done'), ('cancelled', 'Cancelled')],
        default='planning', required=True, index=True)
    # Lets Planning/Saving plans sort above finished ones without a custom group_expand.
    state_order = fields.Integer(compute='_compute_state_order', store=True)
    image = fields.Image(string='Photo', max_width=512, max_height=512)
    has_image = fields.Boolean(compute='_compute_has_image')
    target_date = fields.Date(string='When', help='Departure date, or when you want to have bought it.')
    date_to = fields.Date(string='Back on', help='Return date (trips only).')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id, required=True)
    notes = fields.Text()

    line_ids = fields.One2many('finance.plan.line', 'plan_id', string='Budget items')
    saving_ids = fields.One2many('finance.saving', 'plan_id', string='Savings')

    budget_amount = fields.Monetary(
        string='Budget', currency_field='currency_id', compute='_compute_amounts', store=True)
    saved_amount = fields.Monetary(
        string='Saved', currency_field='currency_id', compute='_compute_amounts', store=True)
    missing_amount = fields.Monetary(
        string='Still needed', currency_field='currency_id', compute='_compute_amounts', store=True)
    progress = fields.Float(string='Progress (%)', compute='_compute_amounts', store=True)
    paid_amount = fields.Monetary(
        string='Paid out', currency_field='currency_id', compute='_compute_amounts', store=True,
        help='What was taken out of the savings to pay for it.')

    @api.depends('image')
    def _compute_has_image(self):
        for plan in self:
            plan.has_image = bool(plan.image)

    @api.depends('state')
    def _compute_state_order(self):
        order = {'planning': 1, 'saving': 0, 'done': 2, 'cancelled': 3}
        for plan in self:
            plan.state_order = order[plan.state]

    @api.depends('line_ids.amount', 'saving_ids.signed_base', 'saving_ids.move')
    def _compute_amounts(self):
        for plan in self:
            budget = sum(plan.line_ids.mapped('amount'))
            counted = plan.saving_ids.filtered(lambda saving: saving.move != 'payout')
            saved = sum(counted.mapped('signed_base'))
            plan.paid_amount = -sum((plan.saving_ids - counted).mapped('signed_base'))
            plan.budget_amount = budget
            plan.saved_amount = saved
            plan.missing_amount = max(budget - saved, 0.0)
            plan.progress = min(saved / budget * 100.0, 100.0) if budget else 0.0

    def action_start_saving(self):
        self.write({'state': 'saving'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reopen(self):
        self.write({'state': 'planning'})


    # ------------------------------------------------------------------ API for the Plans screen

    def _counted_savings(self):
        return self.saving_ids.filtered(lambda saving: saving.move != 'payout')

    def _card(self):
        """Everything one plan card / the plan window shows."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        Overview = self.env['finance.overview']
        days_left = (self.target_date - today).days if self.target_date else None
        months_left = max(1, math.ceil(days_left / 30.4)) if days_left and days_left > 0 else None
        by_user = defaultdict(float)
        for saving in self._counted_savings():
            by_user[saving.user_id.name] += saving.signed_base
        return {
            'id': self.id,
            'name': self.name,
            'kind': self.kind,
            'state': self.state,
            'image': self.has_image and fields.Datetime.to_string(self.write_date) or False,
            'target_date': fields.Date.to_string(self.target_date) if self.target_date else False,
            'date_to': fields.Date.to_string(self.date_to) if self.date_to else False,
            'days_left': days_left,
            'months_left': months_left,
            'budget': self.budget_amount,
            'saved': self.saved_amount,
            'missing': self.missing_amount,
            'paid': self.paid_amount,
            'progress': self.progress,
            'per_month': self.missing_amount / months_left if months_left else 0.0,
            'notes': self.notes or '',
            'lines': [{'id': line.id, 'name': line.name, 'amount': line.amount} for line in self.line_ids],
            'by_user': [{'name': name, 'amount': amount} for name, amount in sorted(by_user.items()) if amount],
            'history': [{
                'id': saving.id, 'date': fields.Date.to_string(saving.date), 'user': saving.user_id.name,
                'kind': saving.kind, 'move': saving.move or '', 'amount': saving.amount,
                'currency': Overview._currency_info(saving.currency_id), 'base': abs(saving.signed_base),
                'is_foreign': saving.is_foreign,
            } for saving in self.saving_ids.sorted(lambda s: (s.date, s.id), reverse=True)[:8]],
        }

    @api.model
    def get_plans(self):
        """The Plans screen: every plan as a card, grouped by status on the client."""
        plans = self.search([('state', 'in', PLAN_STATES)])
        order = {'saving': 0, 'planning': 1, 'done': 2}
        plans = plans.sorted(lambda p: (order[p.state], p.target_date or fields.Date.to_date('2999-12-31'), p.id))
        return {
            'currency': self.env['finance.overview']._currency_info(),
            'plans': [plan._card() for plan in plans],
        }

    @api.model
    def get_plan(self, plan_id):
        return self.browse(plan_id).exists()._card()

    @api.model
    def save_plan(self, data):
        """Create (no `id`) or update a plan from its window: details, the budget table (replaced
        as a whole) and, when the key is there, the photo (False removes it)."""
        name = (data.get('name') or '').strip()
        if not name:
            raise UserError(_('Give the plan a name.'))
        lines = []
        for line in data.get('lines') or []:
            label = (line.get('name') or '').strip()
            amount = float(line.get('amount') or 0)
            if not label and not amount:
                continue
            if amount <= 0:
                raise UserError(_('Every budget item needs an amount above zero.'))
            lines.append((0, 0, {'name': label or _('Item'), 'amount': amount}))
        vals = {
            'name': name,
            'kind': data.get('kind') if data.get('kind') in ('travel', 'purchase') else 'travel',
            'target_date': data.get('target_date') or False,
            'date_to': data.get('date_to') or False,
            'notes': (data.get('notes') or '').strip() or False,
            'line_ids': [(5, 0, 0)] + lines,
        }
        if 'image' in data:
            vals['image'] = data['image'] or False
        if data.get('id'):
            plan = self.browse(data['id']).exists()
            plan.write(vals)
        else:
            plan = self.create(vals)
        return plan._card()

    def _payout(self):
        """The plan is bought: take what it saved out of the savings (per person and currency),
        so the savings no longer count money that has been spent."""
        self.ensure_one()
        Saving = self.env['finance.saving']
        buckets = defaultdict(lambda: [0.0, 0.0])
        for saving in self._counted_savings():
            bucket = buckets[(saving.user_id.id, saving.currency_id.id)]
            bucket[0] += saving.signed_amount
            bucket[1] += saving.signed_base
        for (user_id, currency_id), (amount, base) in buckets.items():
            if amount <= 0:
                continue
            Saving.create({
                'user_id': user_id, 'currency_id': currency_id, 'kind': 'withdraw', 'amount': amount,
                'rate': base / amount, 'plan_id': self.id, 'move': 'payout',
                'notes': _('Paid for %s', self.name),
            })

    @api.model
    def set_plan_state(self, plan_id, state, payout=False):
        """Move a plan along Planning -> Saving -> Done (or back). Done with `payout` takes its
        money out of the savings; leaving Done gives it back."""
        if state not in PLAN_STATES:
            raise UserError(_('Unknown status.'))
        plan = self.browse(plan_id).exists()
        if plan.state == 'done' and state != 'done':
            plan.saving_ids.filtered(lambda saving: saving.move == 'payout').unlink()
        plan.state = state
        if state == 'done' and payout:
            plan._payout()
        return plan._card()

    # ---- moving money between the general savings and a plan ----

    @api.model
    def _bucket(self, plan, user_id, currency_id):
        """(amount, base) held by one person in one currency, in general savings (`plan` empty)
        or for a plan."""
        domain = [('user_id', '=', user_id), ('currency_id', '=', currency_id),
                  ('plan_id', '=', plan.id or False), ('move', '!=', 'payout')]
        row = self.env['finance.saving'].read_group(domain, ['signed_amount:sum', 'signed_base:sum'], [])
        row = row[0] if row else {}
        return (row.get('signed_amount') or 0.0, row.get('signed_base') or 0.0)

    @api.model
    def get_move_options(self, plan_id):
        """Who holds what in each currency, in general savings and for this plan."""
        plan = self.browse(plan_id).exists()
        Saving = self.env['finance.saving']
        Overview = self.env['finance.overview']
        pairs = set()
        for row in Saving.read_group(
                ['|', ('plan_id', '=', False), ('plan_id', '=', plan.id)], ['signed_amount:sum'],
                ['user_id', 'currency_id'], lazy=False):
            pairs.add((row['user_id'][0], row['currency_id'][0]))
        options = []
        for user_id, currency_id in sorted(pairs):
            general, _base = self._bucket(self.browse(), user_id, currency_id)
            held, _base = self._bucket(plan, user_id, currency_id)
            if general <= 0 and held <= 0:
                continue
            options.append({
                'user_id': user_id,
                'user': self.env['res.users'].browse(user_id).name,
                'currency': Overview._currency_info(self.env['res.currency'].browse(currency_id)),
                'general': general,
                'plan': held,
            })
        return options

    @api.model
    def move_savings(self, plan_id, user_id, currency_id, amount, direction='in'):
        """Move `amount` of one person's savings from general savings into the plan ('in') or
        back ('out'). Two linked entries are made, at the average rate the money was saved at, so
        neither the totals nor the plan's progress jump around."""
        plan = self.browse(plan_id).exists()
        amount = float(amount or 0)
        if amount <= 0:
            raise UserError(_('Enter how much to move.'))
        source = self.browse() if direction == 'in' else plan
        target = plan if direction == 'in' else self.browse()
        have, base = self._bucket(source, user_id, currency_id)
        if amount > have + 0.005:
            raise UserError(_('Only %s is available there.', '%.2f' % have))
        rate = base / have if have else 1.0
        Saving = self.env['finance.saving']
        common = {'user_id': user_id, 'currency_id': currency_id, 'amount': amount, 'rate': rate, 'move': 'transfer'}
        Saving.create({**common, 'kind': 'withdraw', 'plan_id': source.id or False,
                       'notes': _('Moved to %s', plan.name) if direction == 'in' else _('Moved to general savings')})
        Saving.create({**common, 'kind': 'deposit', 'plan_id': target.id or False,
                       'notes': _('From general savings') if direction == 'in' else _('From %s', plan.name)})
        if direction == 'in' and plan.state == 'planning':
            plan.state = 'saving'
        return plan._card()


class FinancePlanLine(models.Model):
    _name = 'finance.plan.line'
    _description = 'Plan Budget Item'
    _order = 'sequence, id'

    plan_id = fields.Many2one('finance.plan', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='What', required=True, help='Flights, hotel, food, the thing itself...')
    currency_id = fields.Many2one(related='plan_id.currency_id')
    amount = fields.Monetary(currency_field='currency_id', required=True)
