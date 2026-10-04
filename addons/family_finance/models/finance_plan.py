from odoo import api, fields, models


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

    @api.depends('image')
    def _compute_has_image(self):
        for plan in self:
            plan.has_image = bool(plan.image)

    @api.depends('state')
    def _compute_state_order(self):
        order = {'planning': 1, 'saving': 0, 'done': 2, 'cancelled': 3}
        for plan in self:
            plan.state_order = order[plan.state]

    @api.depends('line_ids.amount', 'saving_ids.signed_base')
    def _compute_amounts(self):
        for plan in self:
            budget = sum(plan.line_ids.mapped('amount'))
            saved = sum(plan.saving_ids.mapped('signed_base'))
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


class FinancePlanLine(models.Model):
    _name = 'finance.plan.line'
    _description = 'Plan Budget Item'
    _order = 'sequence, id'

    plan_id = fields.Many2one('finance.plan', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='What', required=True, help='Flights, hotel, food, the thing itself...')
    currency_id = fields.Many2one(related='plan_id.currency_id')
    amount = fields.Monetary(currency_field='currency_id', required=True)
