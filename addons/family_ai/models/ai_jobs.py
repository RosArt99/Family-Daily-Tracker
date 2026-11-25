import calendar
import logging
from datetime import date, datetime

import pytz
from dateutil.relativedelta import relativedelta

from odoo import api, models

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'Europe/Warsaw'

# ---- protein nudge
PROTEIN_HOURS = (19, 20, 21)   # local time window; the first hourly run in it decides
PROTEIN_MIN_GAP = 20.0          # grams below the goal before it is worth a message
PROTEIN_MIN_PER_100G = 10.0     # what counts as a protein food
PROTEIN_CANDIDATES = 14
PROTEIN_COMBO_MAX = 3
# Ingredients, not something to eat in the evening as is.
NOT_A_SNACK = ('drożdż', 'droż', 'mąka', 'maka', 'flour', 'kakao', 'cocoa', 'groch', 'fasola', 'soczewica',
               'nasiona', 'chia', 'yeast', 'żelatyna', 'gelatin')

# ---- finance
FORECAST_DAY = 15               # mid-month pace check
FORECAST_HOURS = range(12, 22)
MONTH_REPORT_HOURS = range(10, 22)   # on the 1st, about the month that just ended
FORECAST_OVER_PREVIOUS = 1.15   # without a limit: flag a category heading 15% above last month
FORECAST_MIN_AMOUNT = 100.0     # ...but not for small amounts
# Spent a little every day, so a pace makes sense; everything else is paid in lumps.
PACED_CATEGORIES = ('groceries', 'restaurants', 'personal_care')

CATEGORY_RU = {
    'groceries': 'Продукты',
    'housing': 'Жильё',
    'personal_care': 'Уход за собой',
    'subscriptions': 'Подписки',
    'restaurants': 'Рестораны',
    'clothes': 'Одежда',
    'car': 'Машина',
    'other': 'Другое',
    'total': 'Все траты',
}
MONTHS_RU = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август',
             'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def _money(amount, symbol='zł'):
    return '%s %s' % ('{:,.0f}'.format(amount or 0.0).replace(',', ' '), symbol)


class FamilyAiJobs(models.AbstractModel):
    """The scheduled messages. One hourly cron runs everything; each job checks the person's own
    local time and `period_key`, so a message goes out once, in a sensible hour, even after the
    server was off for a while. All numbers are computed here; Claude only words them."""
    _name = 'family.ai.jobs'
    _description = 'Assistant scheduled messages'

    # ------------------------------------------------------------------ helpers

    @api.model
    def _family_users(self):
        return self.env['res.users'].browse(
            [person['id'] for person in self.env['finance.overview'].get_family_users()])

    @api.model
    def _is_female(self, user):
        profile = self.env['gym.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        return profile.sex == 'female'

    @api.model
    def _person_line(self, user):
        """Who the message is for, so the Russian comes out in the right gender ("Ruslana" is
        not "Ruslan")."""
        first = (user.name or '').split(' ')[0]
        female = self._is_female(user)
        return ('Сообщение для: %s (%s). Обращайся на «ты» в %s роде; имя, если упоминаешь, '
                'пиши ровно так: %s.' % (first, 'женщина' if female else 'мужчина',
                                         'женском' if female else 'мужском', first))

    @api.model
    def _local_now(self, user):
        tz = pytz.timezone(user.tz or DEFAULT_TZ)
        return pytz.utc.localize(datetime.utcnow()).astimezone(tz)

    @api.model
    def _has_device(self, user):
        return bool(self.env['mail.partner.device'].sudo().search_count(
            [('partner_id', '=', user.partner_id.id)]))

    @api.model
    def _cron_hourly(self):
        for user in self._family_users():
            now = self._local_now(user)
            for job in (self._job_protein, self._job_finance_forecast, self._job_finance_month):
                try:
                    with self.env.cr.savepoint():
                        job(user, now)
                except Exception:  # one failing job must not stop the others
                    _logger.exception('family_ai: %s failed for %s', job.__name__, user.name)

    # ------------------------------------------------------------------ protein

    @api.model
    def _protein_facts(self, user, day):
        """None when there is nothing to say; else the numbers for the evening protein tip."""
        profile = self.env['gym.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        if not profile or not profile.protein_goal:
            return None
        meals = self.env['gym.meal_log'].sudo().search([('user_id', '=', user.id), ('date', '=', day)])
        if not meals:
            return None  # nothing logged today: probably just not tracking, not starving
        eaten = sum(meals.mapped('proteins'))
        gap = profile.protein_goal - eaten
        if gap < PROTEIN_MIN_GAP:
            return None
        kcal_left = (profile.calorie_goal or 0) - sum(meals.mapped('calories'))

        # What is at home: food in stock with real protein, best protein per kcal first.
        rows = self.env['groceries.stock_entry'].sudo().read_group(
            [('state', '=', 'in_stock'), ('is_food', '=', True)], ['quantity:sum'], ['product_id'])
        products = self.env['groceries.product'].sudo().browse([row['product_id'][0] for row in rows])
        products = products.filtered(
            lambda p: p.proteins_100g >= PROTEIN_MIN_PER_100G and p.energy_kcal_100g > 0
            and not any(word in (p.name or '').lower() for word in NOT_A_SNACK))
        products = products.sorted(lambda p: -p.proteins_100g / p.energy_kcal_100g)[:PROTEIN_CANDIDATES]
        options = [self._portion(product) for product in products]

        # A realistic evening: up to three different foods in normal portions (one protein
        # shake at most), best protein per kcal first, until the gap is covered.
        combo, covered, kcal = [], 0.0, 0.0
        for option in options:
            if covered >= gap or len(combo) == PROTEIN_COMBO_MAX:
                break
            if option['shake'] and any(o['shake'] for o in combo):
                continue
            combo.append(option)
            covered += option['protein']
            kcal += option['kcal']
        return {
            'goal': profile.protein_goal,
            'eaten': round(eaten),
            'gap': round(gap),
            'kcal_goal': profile.calorie_goal,
            'kcal_left': round(kcal_left),
            'meals': ['%s (%s г белка)' % (meal.name or 'без названия', round(meal.proteins)) for meal in meals],
            'options': options,
            'combo': combo,
            'combo_protein': round(covered),
            'combo_kcal': round(kcal),
            'still_missing': max(0, round(gap - covered)),
        }

    @api.model
    def _portion(self, product):
        """One normal serving of a product: a scoop of protein powder, a smaller piece of fatty
        cheese/sausage, else a 150 g portion."""
        shake = product.proteins_100g >= 60
        grams = 30 if shake else (80 if product.energy_kcal_100g >= 250 else 150)
        return {
            'name': product.name,
            'shake': shake,
            'grams': grams,
            'protein': round(product.proteins_100g * grams / 100.0, 1),
            'kcal': round(product.energy_kcal_100g * grams / 100.0),
        }

    @api.model
    def _job_protein(self, user, now, force=False):
        if not force and now.hour not in PROTEIN_HOURS:
            return
        key = 'protein:%s' % now.date().isoformat()
        Message = self.env['family.ai.message']
        if not force and (Message._already_sent(user, key) or not self._has_device(user)):
            return
        facts = self._protein_facts(user, now.date())
        if not facts:
            return
        title = 'Белок: не хватает %s г' % facts['gap']

        def line(o):
            return '- %s: %s г -> %s г белка, %s ккал' % (o['name'], o['grams'], round(o['protein']), o['kcal'])

        prompt = (
            "Вечерняя подсказка по белку. {person}\n"
            "Норма белка {goal} г, съедено {eaten} г, не хватает {gap} г.\n"
            "Калорий осталось до цели: {kcal_left} ккал (цель {kcal_goal}).\n"
            "Сегодня в дневнике: {meals_text}.\n"
            "Предлагаемый набор из того, что есть дома (уже посчитано), всего {combo_protein} г белка "
            "и {combo_kcal} ккал{rest}:\n{combo}\n"
            "Другие варианты дома (порция -> белок, ккал):\n{others}\n\n"
            "Напиши 2-4 коротких предложения: сколько не хватает и предложи этот набор (можно "
            "заменить одну позицию на вариант из второго списка, если он заметно лучше подходит по "
            "калориям). Названия продуктов можно сократить или перевести на русский. "
            "Бери граммы, белок и ккал только из списков."
        ).format(
            person=self._person_line(user), meals_text=', '.join(facts['meals']) or '-',
            combo='\n'.join(line(o) for o in facts['combo']) or '-',
            others='\n'.join(line(o) for o in facts['options'] if o not in facts['combo']) or '-',
            rest=(', после него всё ещё не хватит %s г' % facts['still_missing']) if facts['still_missing'] else '',
            **{k: facts[k] for k in ('goal', 'eaten', 'gap', 'kcal_left', 'kcal_goal', 'combo_protein', 'combo_kcal')})
        text = self.env['family.ai']._ask(prompt, max_tokens=1200)
        if not text:
            text = 'До нормы белка не хватает %s г. Можно так: %s.' % (
                facts['gap'], ', '.join('%s %s г' % (o['name'], o['grams']) for o in facts['combo']) or '-')
        Message._post(user, 'protein', title, text, period_key=key)

    # ------------------------------------------------------------------ finance

    @api.model
    def _overview(self, user, year, month):
        return self.env['finance.overview'].with_user(user).sudo().get_overview(year, month)

    @api.model
    def _job_finance_forecast(self, user, now, force=False):
        """Mid-month: at this pace, which categories end the month over their limit (or, with no
        limit set, well above last month)? Silent when everything looks fine."""
        if not force and (now.day != FORECAST_DAY or now.hour not in FORECAST_HOURS):
            return
        key = 'finance_forecast:%04d-%02d' % (now.year, now.month)
        Message = self.env['family.ai.message']
        if not force and Message._already_sent(user, key):
            return
        today = now.date()
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        elapsed = today.day
        current = self._overview(user, today.year, today.month)
        prev_day = today.replace(day=1) - relativedelta(months=1)
        previous = self._overview(user, prev_day.year, prev_day.month)
        prev_amounts = {}
        if previous['income']['total']:  # only a month that was fully tracked is a fair yardstick
            prev_amounts = {row['key']: row['amount'] for row in previous['expenses']['rows']}
            prev_amounts['total'] = previous['spent']
        symbol = current['currency']['symbol'] or 'zł'

        flags = []
        paced_total = 0.0
        for row in current['expenses']['rows']:
            key, spent, limit = row['key'], row['amount'], row['limit']['limit']
            if key in PACED_CATEGORIES:
                # Everyday spending: project the pace so far to the whole month.
                expected = spent / elapsed * days_in_month
                paced_total += expected
                wording = 'при таком темпе к концу месяца будет около %s' % _money(expected, symbol)
            else:
                # Rent, subscriptions, a jacket, car repairs: paid in lumps, so only what has
                # actually been paid counts - no projection.
                expected = spent
                paced_total += spent
                wording = 'это уже оплачено, без прогноза'
            self._flag(flags, CATEGORY_RU[key], spent, expected, limit, prev_amounts.get(key), wording, symbol)
        total_limit = current['limits']['total']['limit']
        self._flag(flags, CATEGORY_RU['total'], current['spent'], paced_total, total_limit,
                   prev_amounts.get('total'), 'ожидаемо к концу месяца около %s' % _money(paced_total, symbol), symbol)
        if not flags:
            return
        month = MONTHS_RU[today.month]
        prompt = (
            "Прогноз трат семьи на середину месяца ({month}, прошло {elapsed} из {days} дней). {person}\n"
            "Что идёт быстрее, чем нужно (всё уже посчитано):\n{flags}\n\n"
            "Напиши 2-4 коротких предложения: что именно может выйти за рамки и один практичный "
            "совет на оставшиеся дни. Без упрёков, спокойно. Используй только эти цифры."
        ).format(month=month, elapsed=elapsed, days=days_in_month, person=self._person_line(user),
                 flags='\n'.join('- ' + f for f in flags))
        text = self.env['family.ai']._ask(prompt, max_tokens=1200)
        if not text:
            text = 'Середина месяца, при таком темпе:\n' + '\n'.join('• ' + f for f in flags)
        Message._post(user, 'finance_forecast', 'Финансы: прогноз на %s' % month, text, period_key=key)

    @api.model
    def _flag(self, flags, label, spent, expected, limit, previous, wording, symbol):
        """Add a line when `expected` (end-of-month estimate) is over the limit, or - with no
        limit - well above last month."""
        if limit and expected > limit:
            flags.append('%s: потрачено %s, %s; лимит %s' % (label, _money(spent, symbol), wording, _money(limit, symbol)))
        elif not limit and previous and expected >= FORECAST_MIN_AMOUNT \
                and expected > previous * FORECAST_OVER_PREVIOUS:
            flags.append('%s: потрачено %s, %s; в прошлом месяце было %s'
                         % (label, _money(spent, symbol), wording, _money(previous, symbol)))

    @api.model
    def _month_verdict(self, income, spent, saved):
        """(label, share of income left) - decided here, not by the model."""
        if not income:
            return None, None
        kept = (income - spent) / income
        if kept >= 0.30:
            return 'отличный', kept
        if kept >= 0.15:
            return 'хороший', kept
        if kept >= 0:
            return 'напряжённый', kept
        return 'в минус', kept

    @api.model
    def _job_finance_month(self, user, now, force=False):
        """On the 1st: how the month that just ended went, for the family and for this person."""
        if not force and (now.day != 1 or now.hour not in MONTH_REPORT_HOURS):
            return
        last = now.date().replace(day=1) - relativedelta(months=1)
        key = 'finance_month:%04d-%02d' % (last.year, last.month)
        Message = self.env['family.ai.message']
        if not force and Message._already_sent(user, key):
            return
        data = self._overview(user, last.year, last.month)
        if not data['income']['total'] and not data['spent']:
            return
        before = last - relativedelta(months=1)
        prev = self._overview(user, before.year, before.month)
        symbol = data['currency']['symbol'] or 'zł'
        income, spent, saved = data['income']['total'], data['spent'], data['saved']
        verdict, kept = self._month_verdict(income, spent, saved)
        # Comparing with a month in which income was not recorded yet (tracking had not started)
        # gives nonsense like "+796%", so only compare with a fully tracked month.
        prev_tracked = bool(prev['income']['total'])
        prev_amounts = {row['key']: row['amount'] for row in prev['expenses']['rows']} if prev_tracked else {}
        categories = sorted(data['expenses']['rows'], key=lambda r: -r['amount'])
        cat_lines = []
        for row in categories:
            if not row['amount']:
                continue
            was = prev_amounts.get(row['key']) or 0.0
            change = ''
            if was:
                change = ' (месяцем раньше %s, %+d%%)' % (_money(was, symbol), round((row['amount'] - was) / was * 100))
            limit = row['limit']['limit']
            over = (' - лимит %s превышен' % _money(limit, symbol)) if limit and row['amount'] > limit else ''
            cat_lines.append('- %s: %s%s%s' % (CATEGORY_RU[row['key']], _money(row['amount'], symbol), change, over))
        me = next((p for p in data['people'] if p['id'] == user.id), None)
        crypto = data.get('crypto') or {}
        month = MONTHS_RU[last.month]
        facts = [
            'Месяц: %s %s.' % (month, last.year),
            'Доход семьи: %s, траты семьи: %s.' % (_money(income, symbol), _money(spent, symbol)),
        ]
        if prev_tracked:
            facts.append('Месяцем раньше: доход %s, траты %s.' % (
                _money(prev['income']['total'], symbol), _money(prev['spent'], symbol)))
        if verdict:
            facts.append('Оценка месяца (уже решена): %s - осталось %d%% дохода после трат.' % (verdict, round(kept * 100)))
        else:
            facts.append('Дохода в этом месяце не записано, оценку не ставим.')
        if me:
            paid = 'заплатила' if self._is_female(user) else 'заплатил'
            facts.append('Лично %s: доход %s, %s %s, осталось %s.' % (
                user.name.split(' ')[0], _money(me['income'], symbol), paid, _money(me['spent'], symbol),
                _money(me['left'], symbol)))
        if crypto.get('has_lots'):
            facts.append('Крипто-портфель сейчас: $%s, вложено $%s, результат %s$%s (%+.1f%%).' % (
                '{:,.0f}'.format(crypto['value']).replace(',', ' '), '{:,.0f}'.format(crypto['cost']).replace(',', ' '),
                '+' if crypto['pnl'] >= 0 else '-', '{:,.0f}'.format(abs(crypto['pnl'])).replace(',', ' '), crypto['pnl_pct']))
        prompt = (
            "Итог месяца по финансам семьи. {person}\n{facts}\nТраты по категориям:\n{cats}\n"
            "\n"
            "Напиши итог в 4-6 предложениях: начни с оценки месяца (используй её как есть), "
            "назови 1-2 главные категории и что заметно выросло или снизилось, скажи пару слов "
            "о личных цифрах (и о крипте одной фразой, если она есть), закончи одним коротким советом на новый месяц. "
            "Используй только эти цифры, ничего не пересчитывай."
        ).format(person=self._person_line(user), facts='\n'.join(facts), cats='\n'.join(cat_lines) or '-')
        text = self.env['family.ai']._ask(prompt, max_tokens=1500)
        if not text:
            text = '\n'.join(facts[1:] + cat_lines)
        title = 'Итог: %s%s' % (month, (' - %s' % verdict) if verdict else '')
        Message._post(user, 'finance_month', title, text, period_key=key)

    # ------------------------------------------------------------------ manual runs (testing)

    @api.model
    def run_now(self, job, user_id=None):
        """Send one job's message right now, ignoring the hour and the once-only check:
        env['family.ai.jobs'].run_now('protein', 12) from an Odoo shell."""
        user = self.env['res.users'].browse(user_id) if user_id else self.env.user
        method = {'protein': self._job_protein, 'forecast': self._job_finance_forecast,
                  'month': self._job_finance_month}[job]
        method(user, self._local_now(user), force=True)
        return self.env['family.ai.message'].sudo().search([('user_id', '=', user.id)], limit=1).read(
            ['title', 'body', 'create_date'])
