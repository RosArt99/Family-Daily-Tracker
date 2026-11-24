import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class GroceriesShoppingList(models.AbstractModel):
    _inherit = 'groceries.shopping_list'

    @api.model
    def _classify_names(self, names):
        """Which store section each new word belongs to ("chicken thighs" -> Meat & fish,
        "куриные бедра" too), asked once per word; the answer is remembered on the item."""
        Section = self.env['groceries.shopping_section']
        sections = Section.search([])
        if not names or not sections or not self.env['family.ai']._is_configured():
            return super()._classify_names(names)
        by_key = {'s%d' % section.id: section for section in sections}
        catalogue = '\n'.join('%s: %s (%s)' % (key, section.name, section.hint or '') for key, section in by_key.items())
        items = '\n'.join('%d. %s' % (index, name) for index, name in enumerate(names))
        schema = {
            'type': 'object',
            'properties': {
                'sections': {
                    'type': 'array',
                    'description': 'One entry per item.',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'item': {'type': 'integer', 'description': 'The item number.'},
                            'section': {'type': 'string', 'enum': list(by_key)},
                        },
                        'required': ['item', 'section'],
                        'additionalProperties': False,
                    },
                },
            },
            'required': ['sections'],
            'additionalProperties': False,
        }
        text = self.env['family.ai']._ask(
            'Sort these shopping list items (any language; a name may carry its product categories in '
            'brackets) into the store sections of a Polish supermarket.\n\nSections:\n%s\n\nItems:\n%s\n\n'
            'Return the section key for every item number.' % (catalogue, items),
            system='You sort grocery shopping list items into store sections. Reply only with the JSON.',
            max_tokens=2000, schema=schema)
        try:
            answers = json.loads(text or '{}').get('sections') or []
        except ValueError:
            _logger.warning('family_ai: could not read the section answer: %r', text)
            answers = []
        # Matched by item number, not position: a skipped item must not shift all the others.
        result = {}
        for answer in answers:
            index, key = answer.get('item'), answer.get('section')
            if isinstance(index, int) and 0 <= index < len(names) and key in by_key:
                result[names[index]] = by_key[key]
        return result
