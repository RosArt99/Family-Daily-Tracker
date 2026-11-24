import json
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .ai_client import MODEL
from .ai_jobs import CATEGORY_RU, MONTHS_RU, _money

_logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_STORED_MESSAGES = 40       # API messages kept per conversation
NEW_CHAT_AFTER = timedelta(hours=6)   # a question after a long pause starts a fresh conversation
WEEKDAYS_RU = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']

CHAT_SYSTEM = """You are the family assistant inside a private home app used by two people (a couple) on their iPhones.
You can look things up with tools: what is in stock at home (groceries), the shopping list, meals and nutrition, weight, and family finances (amounts in the family's base currency).

How to answer:
- Always answer in Russian, informal ("ты"); speak of yourself in the masculine ("добавил", "нашёл"). Short and to the point: usually 1-5 sentences or a short list. Plain text: no markdown headings, no tables, no bold.
- Look things up before answering questions about data; never guess numbers or products. Quote numbers exactly as the tools give them; if you add things up, say it is approximate.
- Product names in the data are often Polish or English: understand them and you may translate them in your answer.
- For "what do we have ..." questions, check the stock (call stock_products once without a search to see everything, then pick what fits).
- Shopping list: when it would help (something is missing, running out, or the user plans to cook), you may suggest adding things and ASK. Call add_to_shopping_list only after the user clearly agreed in their latest message ("да", "добавь" ...), and only with what they agreed to. The list holds plain generic words in English, lowercase, the way the family writes it ("milk", "eggs", "garlic", "buckwheat", "chicken breast") - never brands or exact product names, and do not ask which brand.
- You cannot change anything else (meals, finances, stock). If asked, say where in the app to do it.
"""

TOOLS = [
    {
        'name': 'stock_products',
        'description': 'Products currently in stock at home (packs not yet finished), with categories and '
                       'nutrition per 100 g. Without `search` returns everything in stock.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'search': {'type': 'string', 'description': 'Optional: words to look for in the product '
                           'name or category, separated by "|" (any matches), e.g. "piwo|beer|пиво".'},
            },
            'additionalProperties': False,
        },
    },
    {
        'name': 'shopping_list',
        'description': 'What is on the shopping list right now (not bought yet).',
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'add_to_shopping_list',
        'description': 'Add products to the shopping list. Only after the user explicitly agreed in their latest message.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'names': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1,
                          'description': 'Plain generic English words, lowercase: "milk", "eggs", "garlic". No brands.'},
            },
            'required': ['names'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'nutrition',
        'description': 'Food diary: daily calories, protein, carbs, fat against the daily goals, and the entries of each day.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'person': {'type': 'string', 'enum': ['me', 'partner']},
                'date_from': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'date_to': {'type': 'string', 'description': 'YYYY-MM-DD, inclusive'},
            },
            'required': ['person', 'date_from', 'date_to'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'weight',
        'description': 'Weigh-ins of a person over the last `days` days, and the weight goal.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'person': {'type': 'string', 'enum': ['me', 'partner']},
                'days': {'type': 'integer', 'minimum': 1, 'maximum': 730},
            },
            'required': ['person', 'days'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'finance_month',
        'description': 'Family finances for one calendar month: income (total and per person), spending by '
                       'category with limits, money put into savings, what is left per person, plans being saved for.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'year': {'type': 'integer'},
                'month': {'type': 'integer', 'minimum': 1, 'maximum': 12},
            },
            'required': ['year', 'month'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'expenses',
        'description': 'Individual payments between two dates: grocery receipts (store, total, household part), '
                       'housing payments and other expenses (title, category), with who paid.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'date_from': {'type': 'string', 'description': 'YYYY-MM-DD'},
                'date_to': {'type': 'string', 'description': 'YYYY-MM-DD, inclusive'},
                'category': {'type': 'string', 'enum': list(CATEGORY_RU)[:-1],
                             'description': 'Optional: only this category.'},
            },
            'required': ['date_from', 'date_to'],
            'additionalProperties': False,
        },
    },
]


def _block_to_dict(block):
    """A response content block as plain JSON-able dict, exactly as it must be sent back
    (thinking blocks included, with their signatures)."""
    if hasattr(block, 'to_dict'):
        return block.to_dict()
    return block.model_dump(exclude_none=True)


class FamilyAiChat(models.Model):
    """One running conversation per person with the assistant. The full API transcript (tool
    calls included) is kept so a follow-up like "да, добавь" has its context."""
    _name = 'family.ai.chat'
    _description = 'Assistant chat'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade',
                              default=lambda self: self.env.user)
    api_messages = fields.Text(default='[]')
    display = fields.Text(default='[]')   # [{role, text}] for the chat window
    last_at = fields.Datetime()

    _sql_constraints = [('user_uniq', 'unique(user_id)', 'One chat per person.')]

    @api.model
    def _mine(self):
        chat = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return chat or self.sudo().create({'user_id': self.env.uid})

    # ------------------------------------------------------------------ screen API

    @api.model
    def get_chat(self):
        chat = self._mine()
        if chat.last_at and fields.Datetime.now() - chat.last_at > NEW_CHAT_AFTER:
            chat._reset()
        return {'messages': json.loads(chat.display or '[]'),
                'configured': self.env['family.ai']._is_configured()}

    @api.model
    def reset_chat(self):
        self._mine()._reset()
        return {'messages': []}

    @api.model
    def send(self, text):
        text = (text or '').strip()
        if not text:
            raise UserError(_('Напиши вопрос.'))
        chat = self._mine()
        if chat.last_at and fields.Datetime.now() - chat.last_at > NEW_CHAT_AFTER:
            chat._reset()
        display = json.loads(chat.display or '[]')
        messages = json.loads(chat.api_messages or '[]')
        messages.append({'role': 'user', 'content': text})
        display.append({'role': 'user', 'text': text})
        answer, messages, changed = chat._run(messages)
        display.append({'role': 'assistant', 'text': answer})
        chat.write({
            'api_messages': json.dumps(self._trim(messages), ensure_ascii=False),
            'display': json.dumps(display[-60:], ensure_ascii=False),
            'last_at': fields.Datetime.now(),
        })
        return {'messages': display, 'changed': changed}

    def _reset(self):
        self.write({'api_messages': '[]', 'display': '[]', 'last_at': False})

    @staticmethod
    def _trim(messages):
        """Keep the tail of the conversation, starting at a plain user question (never at a
        tool result, which would point to a tool call that is no longer there)."""
        if len(messages) <= MAX_STORED_MESSAGES:
            return messages
        tail = messages[-MAX_STORED_MESSAGES:]
        for index, message in enumerate(tail):
            if message['role'] == 'user' and isinstance(message['content'], str):
                return tail[index:]
        return messages[-2:]

    # ------------------------------------------------------------------ the model loop

    def _system(self):
        Jobs = self.env['family.ai.jobs']
        me = self.user_id
        partner = self._partner()
        today = fields.Date.context_today(self.with_user(me))
        who = 'Ты говоришь с: %s (%s).' % (me.name.split(' ')[0], 'женщина' if Jobs._is_female(me) else 'мужчина')
        if partner:
            who += ' Партнёр ("partner" в инструментах): %s (%s).' % (
                partner.name.split(' ')[0], 'женщина' if Jobs._is_female(partner) else 'мужчина')
        return CHAT_SYSTEM + '\n%s\nСегодня %s, %s.' % (who, today.isoformat(), WEEKDAYS_RU[today.weekday()])

    def _run(self, messages):
        """Ask, run the tools Claude calls, repeat until it answers. Returns
        (answer text, updated messages, whether the shopping list changed)."""
        Ai = self.env['family.ai']
        if not Ai._is_configured():
            return 'Помощник не настроен: на сервере нет ключа ANTHROPIC_API_KEY.', messages[:-1], False
        import anthropic

        client = anthropic.Anthropic(timeout=60.0, max_retries=2)
        system = self._system()
        # On failure the question and any half-finished tool round are dropped from the
        # transcript (the chat window still shows the question and the error).
        before = messages[:-1]
        changed = False
        for _round in range(MAX_TOOL_ROUNDS):
            try:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=4000,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                    output_config={'effort': 'low'},
                    cache_control={'type': 'ephemeral'},
                )
            except anthropic.APIStatusError as e:
                _logger.error('family_ai chat: API error %s: %s', e.status_code, e)
                return 'Помощник сейчас недоступен (ошибка %s). Попробуй позже.' % e.status_code, before, changed
            except anthropic.APIConnectionError as e:
                _logger.warning('family_ai chat: no connection: %s', e)
                return 'Нет связи с помощником. Попробуй ещё раз.', before, changed

            usage = response.usage
            _logger.info('family_ai chat: %s in (+%s cached) / %s out tokens', usage.input_tokens,
                         getattr(usage, 'cache_read_input_tokens', 0) or 0, usage.output_tokens)
            if response.stop_reason == 'refusal':
                return 'На это я ответить не могу.', before, changed
            messages.append({'role': 'assistant', 'content': [_block_to_dict(b) for b in response.content]})
            tool_uses = [b for b in response.content if b.type == 'tool_use']
            if response.stop_reason != 'tool_use' or not tool_uses:
                text = ''.join(b.text for b in response.content if b.type == 'text').strip()
                # The chat shows plain text: drop markdown emphasis if the model used it anyway.
                text = text.replace('**', '').replace('__', '')
                return text or '…', messages, changed
            results = []
            for tool in tool_uses:
                try:
                    content = self._tool(tool.name, dict(tool.input or {}))
                    if tool.name == 'add_to_shopping_list':
                        changed = True
                    results.append({'type': 'tool_result', 'tool_use_id': tool.id, 'content': content})
                except Exception as e:  # report to the model, let it recover or explain
                    _logger.exception('family_ai chat: tool %s failed', tool.name)
                    results.append({'type': 'tool_result', 'tool_use_id': tool.id,
                                    'content': 'Error: %s' % e, 'is_error': True})
            messages.append({'role': 'user', 'content': results})
        return 'Не получилось найти ответ, попробуй спросить проще.', before, changed

    # ------------------------------------------------------------------ tools

    def _partner(self):
        family = self.env['family.ai.jobs']._family_users()
        return (family - self.user_id)[:1]

    def _person(self, person):
        return self._partner() if person == 'partner' and self._partner() else self.user_id

    def _tool(self, name, args):
        handler = {
            'stock_products': self._tool_stock,
            'shopping_list': self._tool_shopping_list,
            'add_to_shopping_list': self._tool_add,
            'nutrition': self._tool_nutrition,
            'weight': self._tool_weight,
            'finance_month': self._tool_finance_month,
            'expenses': self._tool_expenses,
        }.get(name)
        if not handler:
            raise ValueError('unknown tool %s' % name)
        return handler(**args)

    def _tool_stock(self, search=None):
        Entry = self.env['groceries.stock_entry'].sudo()
        rows = Entry.read_group([('state', '=', 'in_stock')], ['quantity:sum'], ['product_id'])
        counts = {row['product_id'][0]: row['product_id_count'] for row in rows}
        products = self.env['groceries.product'].sudo().browse(list(counts))
        words = [w.strip().lower() for w in (search or '').split('|') if w.strip()]
        lines = []
        for product in products.sorted('name'):
            categories = ', '.join(product.category_ids[:4].mapped('name'))
            if words and not any(w in (product.name or '').lower() or w in categories.lower() for w in words):
                continue
            line = '%s | packs: %s | %s' % (product.name, counts[product.id], categories or ('food' if product.is_food else 'household'))
            if product.is_food and product.energy_kcal_100g:
                line += ' | per 100 g: %d kcal, protein %.0f, sugars %.0f, fat %.0f' % (
                    product.energy_kcal_100g, product.proteins_100g, product.sugars_100g, product.fat_100g)
            lines.append(line)
        if not lines:
            return 'Nothing in stock matches "%s".' % search if search else 'Nothing in stock.'
        return '%d products in stock:\n%s' % (len(lines), '\n'.join(lines))

    def _tool_shopping_list(self):
        lines = self.env['groceries.shopping_list'].with_user(self.user_id).get_list()['lines']
        if not lines:
            return 'The shopping list is empty.'
        return 'On the shopping list:\n' + '\n'.join('- %s x%s%s' % (
            line['name'], line['count'], ' (already bought today)' if line['done'] else '') for line in lines)

    def _tool_add(self, names):
        added = self.env['groceries.shopping_list'].with_user(self.user_id).add_names(names)
        return 'Added to the shopping list: %s' % ', '.join(added) if added else 'Nothing added.'

    def _tool_nutrition(self, person, date_from, date_to):
        user = self._person(person)
        start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        if (end - start).days > 62:
            start = end - timedelta(days=62)
        profile = self.env['gym.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        meals = self.env['gym.meal_log'].sudo().search(
            [('user_id', '=', user.id), ('date', '>=', start), ('date', '<=', end)], order='date, id')
        out = ['%s, goals per day: %s kcal, protein %s g, carbs %s g, fat %s g.' % (
            user.name.split(' ')[0], profile.calorie_goal, profile.protein_goal, profile.carbs_goal, profile.fat_goal)]
        if not meals:
            return out[0] + ' No diary entries between %s and %s.' % (start, end)
        days = {}
        for meal in meals:
            days.setdefault(meal.date, self.env['gym.meal_log'])
            days[meal.date] |= meal
        detailed = len(days) <= 3
        for day, entries in days.items():
            out.append('%s: %d kcal, protein %.0f g, carbs %.0f g, fat %.0f g (%d entries)' % (
                day, sum(entries.mapped('calories')), sum(entries.mapped('proteins')),
                sum(entries.mapped('carbs')), sum(entries.mapped('fat')), len(entries)))
            if detailed:
                for meal in entries:
                    out.append('  - %s: %s, %.0f g -> %d kcal, protein %.0f g' % (
                        meal.meal_type, meal.name or '?', meal.quantity_g, meal.calories, meal.proteins))
        return '\n'.join(out)

    def _tool_weight(self, person, days):
        user = self._person(person)
        since = fields.Date.context_today(self) - timedelta(days=days)
        logs = self.env['gym.weight_log'].sudo().search(
            [('user_id', '=', user.id), ('date', '>=', since)], order='date, id')
        profile = self.env['gym.profile'].sudo().search([('user_id', '=', user.id)], limit=1)
        head = '%s: target weight %s kg.' % (user.name.split(' ')[0], profile.target_weight or 'not set')
        if not logs:
            return head + ' No weigh-ins in the last %d days.' % days
        return head + '\n' + '\n'.join('%s: %.1f kg' % (log.date, log.weight) for log in logs)

    def _tool_finance_month(self, year, month):
        data = self.env['finance.overview'].with_user(self.user_id).sudo().get_overview(year, month)
        symbol = data['currency']['symbol'] or 'zł'
        out = ['%s %s:' % (MONTHS_RU[month], year),
               'Income %s, spent %s, put into savings %s, left %s.' % (
                   _money(data['income']['total'], symbol), _money(data['spent'], symbol),
                   _money(data['saved'], symbol), _money(data['balance'], symbol)),
               'By category:']
        for row in data['expenses']['rows']:
            limit = row['limit']['limit']
            out.append('- %s: %s%s' % (CATEGORY_RU[row['key']], _money(row['amount'], symbol),
                                       (' (limit %s)' % _money(limit, symbol)) if limit else ''))
        out.append('Groceries split: food %s, household %s.' % (
            _money(data['groceries']['food'], symbol), _money(data['groceries']['household'], symbol)))
        for person in data['people']:
            out.append('%s: income %s, paid %s, saved %s, left %s.' % (
                person['name'].split(' ')[0], _money(person['income'], symbol), _money(person['spent'], symbol),
                _money(person['saved'], symbol), _money(person['left'], symbol)))
        for plan in data['plans']:
            out.append('Plan "%s": saved %s of %s (%d%%).' % (
                plan['name'], _money(plan['saved'], symbol), _money(plan['budget'], symbol), round(plan['progress'] or 0)))
        return '\n'.join(out)

    def _tool_expenses(self, date_from, date_to, category=None):
        start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        symbol = self.env.company.currency_id.symbol or 'zł'
        rows = []
        if category in (None, 'groceries', 'personal_care'):
            for bill in self.env['finance.bill'].sudo().search([('date', '>=', start), ('date', '<=', end)], order='date'):
                rows.append((bill.date, 'Продукты (чек) %s: %s, из них для дома %s, уход %s - платил(а) %s' % (
                    bill.store_id.name or '', _money(bill.total_base, symbol), _money(bill.household_base, symbol),
                    _money(bill.personal_base, symbol), bill.user_id.name.split(' ')[0])))
        if category in (None, 'housing'):
            for pay in self.env['finance.housing'].sudo().search([('period', '>=', start.replace(day=1)), ('period', '<=', end)], order='date'):
                rows.append((pay.date, 'Жильё (%s, за %s): %s - платил(а) %s' % (
                    pay.kind, pay.period.strftime('%Y-%m'), _money(pay.amount_base, symbol), pay.user_id.name.split(' ')[0])))
        if category not in ('groceries', 'housing'):
            domain = [('date', '>=', start), ('date', '<=', end)]
            if category:
                domain.append(('category', '=', category))
            for exp in self.env['finance.expense'].sudo().search(domain, order='date'):
                rows.append((exp.date, '%s: %s %s - платил(а) %s' % (
                    CATEGORY_RU.get(exp.category, exp.category), exp.title or '', _money(exp.amount_base, symbol),
                    exp.user_id.name.split(' ')[0])))
        if not rows:
            return 'No payments found.'
        rows.sort(key=lambda r: r[0])
        rows = rows[-150:]
        return '\n'.join('%s %s' % (day, text) for day, text in rows)
