from datetime import date

from odoo import http
from odoo.http import request


class GroceriesScanController(http.Controller):

    # type='json' == a JSON-RPC 2.0 endpoint: the browser (or curl, below) POSTs
    # {"jsonrpc": "2.0", "params": {"barcode": "...", "action": "..."}} and Odoo
    # unpacks "params" straight into this method's keyword arguments.
    # auth='user' means it runs with an active logged-in session (like a
    # dependency-injected "current_user" in FastAPI), so request.env.user is set.
    @http.route('/groceries/scan', type='json', auth='user', methods=['POST'])
    def scan_barcode(self, barcode, action='in_stock'):
        barcode = (barcode or '').strip()
        if not barcode:
            return {'error': 'Barcode is empty.'}
        if action not in ('to_buy', 'in_stock', 'consumed'):
            return {'error': 'Unknown action: %s' % action}

        Product = request.env['groceries.product']
        StockEntry = request.env['groceries.stock_entry']

        product, created = Product.create_from_barcode(barcode)

        entry = StockEntry
        if action == 'in_stock':
            entry = StockEntry.search(
                [('product_id', '=', product.id), ('state', '=', 'to_buy')], limit=1)
            if entry:
                entry.action_mark_purchased()
        elif action == 'consumed':
            entry = StockEntry.search(
                [('product_id', '=', product.id), ('state', '=', 'in_stock')], limit=1)
            if entry:
                entry.action_mark_consumed()

        if not entry:
            vals = {'product_id': product.id, 'state': action}
            if action == 'in_stock':
                vals['purchase_date'] = date.today()
            elif action == 'consumed':
                vals['consumed_date'] = date.today()
            entry = StockEntry.create(vals)

        return {
            'product_id': product.id,
            'product_name': product.name,
            'product_created': created,
            'stock_entry_id': entry.id,
            'state': entry.state,
        }
