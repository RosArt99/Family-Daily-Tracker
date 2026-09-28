from datetime import date

from odoo import http
from odoo.http import request

MAX_COUNT = 999


class GroceriesScanController(http.Controller):

    # type='json' == a JSON-RPC 2.0 endpoint: the browser (or curl, below) POSTs
    # {"jsonrpc": "2.0", "params": {"barcode": "...", "action": "..."}} and Odoo
    # unpacks "params" straight into this method's keyword arguments.
    # auth='user' means it runs with an active logged-in session (like a
    # dependency-injected "current_user" in FastAPI), so request.env.user is set.
    @http.route('/groceries/scan', type='json', auth='user', methods=['POST'])
    def scan_barcode(self, barcode, action='in_stock', count=1):
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': 'Barcode is empty.'}
        if action not in ('to_buy', 'in_stock', 'consumed'):
            return {'error': 'Unknown action: %s' % action}
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(count, MAX_COUNT))

        Product = request.env['groceries.product']
        StockEntry = request.env['groceries.stock_entry']

        product, created = Product.create_from_barcode(barcode)
        today = date.today()

        # One scan of a barcode can stand for several identical physical packs (e.g. a
        # 10-pack of coffee jars scanned once with the counter set to 10): each pack still
        # gets its own entry, so it can later be marked purchased/consumed on its own.
        entry_ids = []
        remaining = count
        if action == 'in_stock':
            # Advance existing "to buy" entries first, oldest first, instead of piling up
            # fresh "in stock" ones next to them.
            to_advance = StockEntry.search(
                [('product_id', '=', product.id), ('state', '=', 'to_buy')],
                order='id', limit=remaining)
            if to_advance:
                to_advance.action_mark_purchased()
                entry_ids += to_advance.ids
                remaining -= len(to_advance)
        elif action == 'consumed':
            to_advance = StockEntry.search(
                [('product_id', '=', product.id), ('state', '=', 'in_stock')],
                order='id', limit=remaining)
            if to_advance:
                to_advance.action_mark_consumed()
                entry_ids += to_advance.ids
                remaining -= len(to_advance)

        if remaining:
            vals = {'product_id': product.id, 'state': action}
            if action == 'in_stock':
                vals['purchase_date'] = today
            elif action == 'consumed':
                vals['consumed_date'] = today
            new_entries = StockEntry.create([vals] * remaining)
            entry_ids += new_entries.ids

        # group_expand on the state field means read_group always returns all three states,
        # even empty ones - whose sum then comes back as False rather than 0.
        totals = {
            row['state']: row['quantity'] or 0.0
            for row in StockEntry.read_group(
                [('product_id', '=', product.id)], ['quantity:sum'], ['state'])
        }

        return {
            'product_id': product.id,
            'product_name': product.name,
            'product_created': created,
            'entry_ids': entry_ids,
            'count': count,
            'state': action,
            'totals': {
                'to_buy': totals.get('to_buy', 0.0),
                'in_stock': totals.get('in_stock', 0.0),
                'consumed': totals.get('consumed', 0.0),
            },
        }
