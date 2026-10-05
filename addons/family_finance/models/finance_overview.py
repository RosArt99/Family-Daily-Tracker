from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from .finance_expense import EXPENSE_CATEGORIES, PLAIN_CATEGORIES


class FinanceOverview(models.AbstractModel):
    _name = 'finance.overview'
    _description = 'Finance Overview (dashboard data)'

    def _currency_info(self, currency=None):
        currency = currency or self.env.company.currency_id
        return {'id': currency.id, 'name': currency.name, 'symbol': currency.symbol,
                'position': currency.position, 'decimals': currency.decimal_places}

    @api.model
    def get_family_users(self):
        """The people the Finance dialogs offer as "who" - real accounts only: the demo data
        users Odoo ships with (Mitchell Admin, Marc Demo) are left out."""
        skip = [
            ref.id for ref in (
                self.env.ref('base.user_admin', raise_if_not_found=False),
                self.env.ref('base.user_demo', raise_if_not_found=False)) if ref]
        users = self.env['res.users'].search(
            [('share', '=', False), ('id', 'not in', skip)], order='name')
        return [{'id': user.id, 'name': user.name} for user in users]

    @api.model
    def get_currencies(self):
        """The company (base) currency and every active currency, for the currency pickers."""
        currencies = self.env['res.currency'].search([('active', '=', True)])
        return {
            'base': self._currency_info(),
            'list': [self._currency_info(c) for c in currencies],
        }

    @api.model
    def get_currency_info(self):
        return self._currency_info()

    @api.model
    def get_overview(self, year=None, month=None):
        """Everything the Overview screen shows for one calendar month, in a single round trip."""
        today = fields.Date.context_today(self)
        first = date(year or today.year, month or today.month, 1)
        nxt = first + relativedelta(months=1)
        Bill = self.env['finance.bill']
        Housing = self.env['finance.housing']
        Income = self.env['finance.income']
        Saving = self.env['finance.saving']

        def bill_totals(start, end):
            rows = Bill.read_group(
                [('date', '>=', start), ('date', '<', end)],
                ['total_base:sum', 'household_base:sum', 'food_base:sum'], [])
            row = rows[0] if rows else {}
            return {
                'total': row.get('total_base') or 0.0,
                'household': row.get('household_base') or 0.0,
                'food': row.get('food_base') or 0.0,
                'count': row.get('__count') or 0,
            }

        def housing_total(start, end):
            # Counted in the month the payment is FOR, not the day it was paid.
            rows = Housing.read_group(
                [('period', '>=', start), ('period', '<', end)], ['amount_base:sum'], [])
            return (rows[0].get('amount_base') if rows else 0.0) or 0.0

        def income_total(start, end):
            rows = Income.read_group(
                [('date', '>=', start), ('date', '<', end)], ['amount_base:sum'], [])
            return (rows[0].get('amount_base') if rows else 0.0) or 0.0

        by_user = [
            {'id': row['user_id'][0], 'name': row['user_id'][1], 'amount': row['amount_base'] or 0.0}
            for row in Income.read_group(
                [('date', '>=', first), ('date', '<', nxt)], ['amount_base:sum'], ['user_id'])
        ]
        by_user.sort(key=lambda r: r['name'])

        groceries = bill_totals(first, nxt)
        housing_sum = housing_total(first, nxt)
        plain = self._plain_expense_totals(first, nxt)
        amounts = {'groceries': groceries['total'], 'housing': housing_sum, **plain}
        income = sum(r['amount'] for r in by_user)
        spent = sum(amounts.values())
        saved = sum(
            row['signed_base'] or 0.0 for row in Saving.read_group(
                [('date', '>=', first), ('date', '<', nxt)], ['signed_base:sum'], []))

        trend = []
        for back in range(5, -1, -1):
            start = first - relativedelta(months=back)
            end = start + relativedelta(months=1)
            trend.append({
                'label': start.strftime('%b'),
                'income': income_total(start, end),
                'spent': bill_totals(start, end)['total'] + housing_total(start, end)
                + sum(self._plain_expense_totals(start, end).values()),
                'current': back == 0,
            })

        limits = self.env['finance.budget'].get_limits()
        spending = {**amounts, 'total': spent}
        limit_rows = [{
            'key': key, 'limit': limits[key], 'spent': spending[key],
            'percent': round(spending[key] / limits[key] * 100.0) if limits[key] else 0,
        } for key in limits]
        limits_by_key = {row['key']: row for row in limit_rows}
        expenses = {
            'total': spent,
            'rows': [{
                'key': key, 'label': EXPENSE_CATEGORIES[key][0], 'icon': EXPENSE_CATEGORIES[key][1],
                'amount': amounts[key], 'limit': limits_by_key[key],
            } for key in EXPENSE_CATEGORIES],
        }

        plans = self.env['finance.plan'].search([('state', 'in', ('planning', 'saving'))], limit=5)

        return {
            'year': first.year,
            'month': first.month,
            'label': first.strftime('%B %Y'),
            'is_current_month': (first.year, first.month) == (today.year, today.month),
            'currency': self._currency_info(),
            'income': {'total': income, 'by_user': by_user},
            'groceries': groceries,
            'expenses': expenses,
            'spent': spent,
            'saved': saved,
            'balance': income - spent - saved,
            'limits': limits_by_key,
            'trend': trend,
            'plans': [{
                'id': plan.id, 'name': plan.name, 'kind': plan.kind, 'state': plan.state,
                'budget': plan.budget_amount, 'saved': plan.saved_amount,
                'progress': plan.progress,
                'target_date': fields.Date.to_string(plan.target_date) if plan.target_date else False,
            } for plan in plans],
        }

    def _plain_expense_totals(self, start, end):
        """Spending per plain category (subscriptions, restaurants, ...) between two dates."""
        totals = dict.fromkeys(PLAIN_CATEGORIES, 0.0)
        for row in self.env['finance.expense'].read_group(
                [('date', '>=', start), ('date', '<', end)], ['amount_base:sum'], ['category']):
            totals[row['category']] = row['amount_base'] or 0.0
        return totals

    @api.model
    def get_savings(self):
        """The Savings screen: what is saved (per currency, and worth how much in the company
        currency today), whose it is, which plan it is for, and the latest transfers."""
        Saving = self.env['finance.saving']
        Fx = self.env['finance.fx.rate']
        Currency = self.env['res.currency']
        today = fields.Date.context_today(self)

        def net_base(domain):
            rows = Saving.read_group(domain, ['signed_base:sum'], [])
            return (rows[0].get('signed_base') if rows else 0.0) or 0.0

        balances = []
        total_now = 0.0
        for row in Saving.read_group([], ['signed_amount:sum'], ['currency_id']):
            currency = Currency.browse(row['currency_id'][0])
            amount = row['signed_amount'] or 0.0
            rate = Fx.get_rate(currency.id, today)['rate'] or 0.0
            base_now = amount * rate
            total_now += base_now
            balances.append({**self._currency_info(currency), 'amount': amount, 'base_now': base_now})
        balances.sort(key=lambda b: -abs(b['base_now']))

        by_user = [
            {'id': row['user_id'][0], 'name': row['user_id'][1], 'amount': row['signed_base'] or 0.0}
            for row in Saving.read_group([], ['signed_base:sum'], ['user_id'])
        ]
        by_user.sort(key=lambda r: r['name'])

        plans = self.env['finance.plan'].search([('saving_ids', '!=', False)])
        by_plan = [{
            'id': plan.id, 'name': plan.name, 'kind': plan.kind, 'state': plan.state,
            'saved': plan.saved_amount, 'budget': plan.budget_amount, 'progress': plan.progress,
        } for plan in plans]

        recent = [{
            'id': rec.id, 'date': fields.Date.to_string(rec.date), 'kind': rec.kind,
            'amount': rec.amount, 'currency': self._currency_info(rec.currency_id),
            'is_foreign': rec.is_foreign, 'base': abs(rec.signed_base), 'user': rec.user_id.name,
            'plan': rec.plan_id.name or '', 'notes': rec.notes or '',
        } for rec in Saving.search([], limit=10)]

        return {
            'currency': self._currency_info(),
            'balances': balances,
            'total_now': total_now,
            'general': net_base([('plan_id', '=', False)]),
            'by_user': by_user,
            'by_plan': by_plan,
            'recent': recent,
        }
