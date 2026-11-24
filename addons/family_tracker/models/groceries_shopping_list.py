from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GroceriesShoppingSection(models.Model):
    """A store department ("Fruit & veg", "Dairy"...). The Shopping List is laid out in this
    order - the way you walk through the store - so nothing makes you walk back."""
    _name = 'groceries.shopping_section'
    _description = 'Store section'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=False)
    sequence = fields.Integer(default=50)
    hint = fields.Char(help='What belongs here, in a few words - helps the assistant sort new items.')
    active = fields.Boolean(default=True)

    @api.model
    def _fallback(self):
        return self.env.ref('family_tracker.section_other', raise_if_not_found=False) or self.search([], order='sequence desc', limit=1)


class GroceriesShoppingItem(models.Model):
    """A plain-words line on the Shopping List: "milk", "garlic", "buckwheat". Not a catalog
    product - in the store you pick whichever milk is there. (A specific product is added by
    scanning its barcode; that one is a "to buy" stock entry instead, see the list below.)"""
    _name = 'groceries.shopping_item'
    _description = 'Shopping list item (plain words)'
    _order = 'create_date, id'

    name = fields.Char(required=True)
    qty = fields.Integer(string='How many', default=1)
    done = fields.Boolean(string='Bought')
    done_date = fields.Date()
    user_id = fields.Many2one('res.users', string='Added by', default=lambda self: self.env.user)
    section_id = fields.Many2one('groceries.shopping_section', string='Store section', ondelete='set null')
    # Cleared items are archived, not deleted: their names feed the suggestions when typing.
    active = fields.Boolean(default=True)


class GroceriesShoppingList(models.AbstractModel):
    """The Shopping List screen: one list mixing plain-words items and specific products added by
    barcode ("to buy" stock entries, one line per product). Ticking a line strikes it through in
    place; for a product it also means bought (In Stock, like scanning at checkout). Ticked lines
    stay visible until "Clear ticked" or the next day."""
    _name = 'groceries.shopping_list'
    _description = 'Shopping list (screen API)'

    # ------------------------------------------------------------------ reading

    @api.model
    def get_list(self):
        today = fields.Date.context_today(self)
        Item = self.env['groceries.shopping_item']
        Entry = self.env['groceries.stock_entry']
        lines = []
        items = Item.search(['|', ('done', '=', False), ('done_date', '=', today)])
        self._sort_into_sections(items.filtered(lambda i: not i.section_id))
        for item in items:
            lines.append({
                'section_id': item.section_id.id,
                'key': 'i%d' % item.id, 'kind': 'item', 'id': item.id, 'name': item.name,
                'count': item.qty, 'done': item.done, 'product_id': False, 'image': False,
                'added_by': (item.user_id.name or '').split(' ')[0],
                'order': fields.Datetime.to_string(item.create_date),
            })
        entries = Entry.search(['|', ('state', '=', 'to_buy'),
                                '&', '&', ('state', '=', 'in_stock'), ('bought_from_list', '=', True),
                                ('purchase_date', '=', today)], order='id')
        grouped = {}
        for entry in entries:
            done = entry.state == 'in_stock'
            grouped.setdefault((entry.product_id, done), Entry)
            grouped[(entry.product_id, done)] |= entry
        self._sort_products_into_sections(
            self.env['groceries.product'].union(*[product for product, _done in grouped]).filtered(
                lambda p: not p.shopping_section_id))
        for (product, done), product_entries in grouped.items():
            first = product_entries.sorted('create_date')[:1]
            lines.append({
                'section_id': product.shopping_section_id.id,
                'key': 'p%d%s' % (product.id, 'd' if done else ''), 'kind': 'product', 'id': product.id,
                'entry_ids': product_entries.ids, 'name': product.name, 'count': len(product_entries),
                'done': done, 'product_id': product.id, 'image': bool(product.image),
                'added_by': (first.user_id.name or '').split(' ')[0],
                'order': fields.Datetime.to_string(first.create_date),
            })
        # By store section (the way through the store), then in the order things were added -
        # ticked or not, so nothing jumps around while shopping.
        sections = self.env['groceries.shopping_section'].search([])
        rank = {section.id: index for index, section in enumerate(sections)}
        fallback = self.env['groceries.shopping_section']._fallback()
        for line in lines:
            line['section_id'] = line['section_id'] or fallback.id
        lines.sort(key=lambda line: (rank.get(line['section_id'], 999), line['order'] or '', line['key']))
        return {
            'lines': lines,
            'sections': [{'id': section.id, 'name': section.name} for section in sections],
        }

    # ------------------------------------------------------------------ store sections

    @api.model
    def _remembered_section(self, name):
        """The section this word went to last time (also after it was moved by hand)."""
        last = self.env['groceries.shopping_item'].with_context(active_test=False).search(
            [('name', '=ilike', name), ('section_id', '!=', False)], order='write_date desc, id desc', limit=1)
        return last.section_id

    @api.model
    def _classify_names(self, names):
        """{name: section} for words never seen before. Plain Groceries has no way to tell;
        family_ai overrides this to ask the assistant. Unknown names go to the fallback section."""
        return {}

    @api.model
    def _sort_into_sections(self, items):
        unknown = {}
        for item in items:
            section = self._remembered_section(item.name)
            if section:
                item.section_id = section
            else:
                unknown.setdefault(item.name.lower(), self.env['groceries.shopping_item'])
                unknown[item.name.lower()] |= item
        if unknown:
            guessed = self._classify_names([group[:1].name for group in unknown.values()])
            fallback = self.env['groceries.shopping_section']._fallback()
            for key, group in unknown.items():
                group.section_id = guessed.get(group[:1].name) or fallback

    @api.model
    def _sort_products_into_sections(self, products):
        """Scanned products: decided once per product, from its name and categories."""
        if not products:
            return
        labels = {}
        for product in products:
            categories = ', '.join(product.category_ids[:3].mapped('name'))
            labels['%s (%s)' % (product.name, categories) if categories else product.name] = product
        guessed = self._classify_names(list(labels))
        fallback = self.env['groceries.shopping_section']._fallback()
        for label, product in labels.items():
            product.shopping_section_id = guessed.get(label) or fallback

    @api.model
    def set_section(self, kind, ident, section_id):
        """Moved to another section by hand - and remembered for next time."""
        section = self.env['groceries.shopping_section'].browse(section_id).exists()
        if kind == 'item':
            item = self.env['groceries.shopping_item'].browse(ident).exists()
            if item and section:
                # Every earlier item with this word follows, so the memory points here now.
                self.env['groceries.shopping_item'].with_context(active_test=False).search(
                    [('name', '=ilike', item.name)]).write({'section_id': section.id})
        else:
            product = self.env['groceries.product'].browse(ident).exists()
            if product and section:
                product.shopping_section_id = section
        return self.get_list()

    @api.model
    def suggest(self, query, limit=6):
        """Names written before (most used first) that start with / contain what is being typed."""
        query = (query or '').strip()
        if not query:
            return []
        rows = self.env['groceries.shopping_item'].with_context(active_test=False).read_group(
            [('name', 'ilike', query)], ['name'], ['name'], orderby='name_count desc', limit=30)
        names = [row['name'] for row in rows]
        lower = query.lower()
        names.sort(key=lambda n: (not n.lower().startswith(lower), n.lower()))
        # Case variants of the same word ("Milk", "milk") show once.
        seen, out = set(), []
        for name in names:
            if name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
        return out[:limit]

    # ------------------------------------------------------------------ changing

    @api.model
    def add_item(self, name):
        """Add "milk": one more of it when it is already on the list (not ticked)."""
        name = ' '.join((name or '').split())
        if not name:
            raise UserError(_('Type what to buy.'))
        Item = self.env['groceries.shopping_item']
        same = Item.search([('name', '=ilike', name), ('done', '=', False)], limit=1)
        if same:
            same.qty += 1
        else:
            item = Item.create({'name': name})
            self._sort_into_sections(item)
        return self.get_list()

    @api.model
    def add_names(self, names):
        """Several plain-words items at once (the assistant's "yes, add them")."""
        added = []
        for name in names or []:
            name = ' '.join((name or '').split())
            if name:
                self.add_item(name)
                added.append(name)
        return added

    @api.model
    def get_sections(self):
        return [{'id': s.id, 'name': s.name} for s in self.env['groceries.shopping_section'].search([])]

    @api.model
    def toggle(self, kind, ident, entry_ids=None):
        """Tick / untick a line. For a product this is buying it (or taking that back)."""
        if kind == 'item':
            item = self.env['groceries.shopping_item'].browse(ident).exists()
            if item:
                done = not item.done
                item.write({'done': done, 'done_date': fields.Date.context_today(self) if done else False})
        else:
            entries = self.env['groceries.stock_entry'].browse(entry_ids or []).exists()
            to_buy = entries.filtered(lambda e: e.state == 'to_buy')
            if to_buy:
                to_buy.action_mark_purchased()
            else:
                entries.filtered(lambda e: e.state == 'in_stock' and e.bought_from_list).write(
                    {'state': 'to_buy', 'purchase_date': False})
        return self.get_list()

    @api.model
    def change_count(self, kind, ident, delta):
        """+1 / -1 on a line; -1 on the last one takes it off the list."""
        if kind == 'item':
            item = self.env['groceries.shopping_item'].browse(ident).exists()
            if item:
                if item.qty + delta <= 0:
                    item.unlink()
                else:
                    item.qty += delta
        else:
            Entry = self.env['groceries.stock_entry']
            if delta > 0:
                Entry.create([{'product_id': ident, 'state': 'to_buy'}] * min(int(delta), 99))
            elif delta < 0:
                Entry.search([('product_id', '=', ident), ('state', '=', 'to_buy')],
                             order='id desc', limit=-int(delta)).unlink()
        return self.get_list()

    @api.model
    def remove(self, kind, ident):
        """Off the list without buying it."""
        if kind == 'item':
            self.env['groceries.shopping_item'].browse(ident).exists().unlink()
        else:
            self.env['groceries.stock_entry'].search(
                [('product_id', '=', ident), ('state', '=', 'to_buy')]).unlink()
        return self.get_list()

    @api.model
    def clear_done(self):
        """Hide everything ticked (bought products stay In Stock, they just leave the list)."""
        self.env['groceries.shopping_item'].search([('done', '=', True)]).write({'active': False})
        self.env['groceries.stock_entry'].search(
            [('state', '=', 'in_stock'), ('bought_from_list', '=', True)]).write({'bought_from_list': False})
        return self.get_list()
