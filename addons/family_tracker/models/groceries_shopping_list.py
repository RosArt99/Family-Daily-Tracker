from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GroceriesShoppingList(models.AbstractModel):
    """The Shopping List screen: "to buy" stock entries shown one line per product, ticked off in
    the store. Ticking = bought (the entries go In Stock, exactly like scanning at checkout), so
    the list and the stock never disagree."""
    _name = 'groceries.shopping_list'
    _description = 'Shopping list (screen API)'

    @api.model
    def _line(self, product, entries):
        return {
            'product_id': product.id,
            'name': product.name,
            'count': len(entries),
            'entry_ids': entries.ids,
            'is_food': product.is_food,
            'image': bool(product.image),
            'categories': product.category_ids[:2].mapped('name'),
            'added_by': entries[:1].user_id.name.split(' ')[0] if entries[:1].user_id else '',
            'stock': product.stock_quantity,
        }

    @api.model
    def get_list(self):
        Entry = self.env['groceries.stock_entry']
        today = fields.Date.context_today(self)
        to_buy = Entry.search([('state', '=', 'to_buy')], order='id')
        bought = Entry.search([('state', '=', 'in_stock'), ('bought_from_list', '=', True),
                               ('purchase_date', '=', today)], order='write_date desc, id desc')

        def grouped(entries):
            lines, seen = [], {}
            for entry in entries:
                seen.setdefault(entry.product_id, Entry)
                seen[entry.product_id] |= entry
            for product, product_entries in seen.items():
                lines.append(self._line(product, product_entries))
            return lines

        return {'to_buy': grouped(to_buy), 'bought': grouped(bought)}

    @api.model
    def search_products(self, query, limit=8):
        """Catalog matches for the "add" box, things you have bought before first."""
        query = (query or '').strip()
        if not query:
            return []
        products = self.env['groceries.product'].search([('name', 'ilike', query)], limit=40)
        products = products.sorted(lambda p: (-len(p.stock_entry_ids), p.name.lower()))[:limit]
        return [{'id': p.id, 'name': p.name, 'image': bool(p.image), 'stock': p.stock_quantity} for p in products]

    @api.model
    def add(self, product_id=None, name=None, count=1):
        """Put a product on the list: an existing one (`product_id`) or by name - the same
        product when the name matches one exactly, else a new catalog entry with just a name."""
        Product = self.env['groceries.product']
        product = Product.browse(product_id).exists() if product_id else Product
        if not product:
            name = (name or '').strip()
            if not name:
                raise UserError(_('Type what to buy.'))
            product = Product.search([('name', '=ilike', name)], limit=1) or Product.create({'name': name})
        count = max(1, min(int(count or 1), 99))
        self.env['groceries.stock_entry'].create([{'product_id': product.id, 'state': 'to_buy'}] * count)
        return self.get_list()

    @api.model
    def add_names(self, names):
        """Several products by name at once (the assistant's "yes, add them")."""
        added = []
        for name in names or []:
            name = (name or '').strip()
            if name:
                self.add(name=name)
                added.append(name)
        return added

    @api.model
    def check(self, entry_ids):
        """Ticked in the store: these packs are bought."""
        entries = self.env['groceries.stock_entry'].browse(entry_ids).exists().filtered(lambda e: e.state == 'to_buy')
        entries.action_mark_purchased()
        return self.get_list()

    @api.model
    def uncheck(self, entry_ids):
        """Tick taken back: back on the list, as if never bought."""
        entries = self.env['groceries.stock_entry'].browse(entry_ids).exists().filtered(
            lambda e: e.state == 'in_stock' and e.bought_from_list)
        entries.write({'state': 'to_buy', 'purchase_date': False})
        return self.get_list()

    @api.model
    def change_count(self, product_id, delta):
        """+1 / -1 pack of a product on the list (removing the last one takes it off the list)."""
        Entry = self.env['groceries.stock_entry']
        if delta > 0:
            Entry.create([{'product_id': product_id, 'state': 'to_buy'}] * min(int(delta), 99))
        elif delta < 0:
            Entry.search([('product_id', '=', product_id), ('state', '=', 'to_buy')],
                         order='id desc', limit=-int(delta)).unlink()
        return self.get_list()

    @api.model
    def remove(self, product_id):
        """Off the list without buying it."""
        self.env['groceries.stock_entry'].search(
            [('product_id', '=', product_id), ('state', '=', 'to_buy')]).unlink()
        return self.get_list()
