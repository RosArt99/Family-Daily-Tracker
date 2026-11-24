from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
        for item in items:
            lines.append({
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
        for (product, done), product_entries in grouped.items():
            first = product_entries.sorted('create_date')[:1]
            lines.append({
                'key': 'p%d%s' % (product.id, 'd' if done else ''), 'kind': 'product', 'id': product.id,
                'entry_ids': product_entries.ids, 'name': product.name, 'count': len(product_entries),
                'done': done, 'product_id': product.id, 'image': bool(product.image),
                'added_by': (first.user_id.name or '').split(' ')[0],
                'order': fields.Datetime.to_string(first.create_date),
            })
        # In the order things were added, ticked or not, so nothing jumps around in the store.
        lines.sort(key=lambda line: (line['order'] or '', line['key']))
        return {'lines': lines}

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
            Item.create({'name': name})
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
