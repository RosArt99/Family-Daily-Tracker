import hashlib
import json

from odoo import _, api, fields, models

# The four numbers Meals and the stock cards are built on; Open Food Facts changing any of them
# (or the product's name) is something a person has to look at before it replaces what we have.
NUTRITION_KEYS = (
    ('energy_kcal_100g', 'kcal'),
    ('proteins_100g', 'protein'),
    ('fat_100g', 'fat'),
    ('carbohydrates_100g', 'carbs'),
)


class GroceriesProductOffUpdate(models.Model):
    """What Open Food Facts now says about a product, when that differs from our catalog in its
    name or its kcal / protein / fat / carbs. Nothing is applied until someone decides: the
    barcode may belong to another product there (store-internal codes are reused between
    countries) or an OFF contributor may have changed it."""
    _name = 'groceries.product.off.update'
    _description = 'Open Food Facts change waiting for a decision'
    _order = 'create_date desc, id desc'
    _rec_name = 'product_id'

    product_id = fields.Many2one('groceries.product', required=True, ondelete='cascade', index=True)
    barcode = fields.Char(related='product_id.barcode')
    state = fields.Selection(
        [('pending', 'To review'), ('applied', 'Updated'), ('dismissed', 'Kept as it was')],
        default='pending', required=True, index=True)
    # Fingerprint of the OFF data being offered: the same offer is never made twice once decided.
    signature = fields.Char(index=True)
    values_json = fields.Text(help='Everything OFF returned, applied as a whole when you accept.')
    changed = fields.Char(string='What changed')

    old_name = fields.Char(string='Name now')
    new_name = fields.Char(string='Name on OFF')
    old_kcal = fields.Float(string='kcal now')
    new_kcal = fields.Float(string='kcal on OFF')
    old_protein = fields.Float(string='Protein now')
    new_protein = fields.Float(string='Protein on OFF')
    old_fat = fields.Float(string='Fat now')
    new_fat = fields.Float(string='Fat on OFF')
    old_carbs = fields.Float(string='Carbs now')
    new_carbs = fields.Float(string='Carbs on OFF')

    @api.model
    def _differences(self, product, vals):
        """The labels of what in `vals` (from OFF) disagrees with `product`: its name, and any of
        kcal/protein/fat/carbs it already has - by more than rounding. A number we have none of
        is simply filled in, and OFF missing a number is not a change."""
        diffs = []
        new_name = (vals.get('name') or '').strip()
        if new_name and new_name.casefold() != (product.name or '').strip().casefold():
            diffs.append(_('Name'))
        labels = {'kcal': _('Calories'), 'protein': _('Protein'), 'fat': _('Fat'), 'carbs': _('Carbs')}
        for field, key in NUTRITION_KEYS:
            current, new = product[field], vals.get(field) or 0.0
            if current and new and abs(current - new) > max(1.0, 0.05 * current):
                diffs.append(labels[key])
        return diffs

    @api.model
    def propose(self, product, vals, diffs):
        """Remember OFF's offer for `product` (one open offer per product). Returns the record, or
        None when this very offer was already decided."""
        key_values = [vals.get('name', '')] + [round(vals.get(field) or 0.0, 1) for field, _key in NUTRITION_KEYS]
        signature = hashlib.sha1(json.dumps(key_values).encode()).hexdigest()
        if self.search_count([('product_id', '=', product.id), ('signature', '=', signature),
                              ('state', '!=', 'pending')]):
            return None
        data = {
            'signature': signature,
            'values_json': json.dumps(vals),
            'changed': ', '.join(diffs),
            'old_name': product.name, 'new_name': vals.get('name') or product.name,
        }
        for field, key in NUTRITION_KEYS:
            data['old_' + key] = product[field]
            data['new_' + key] = vals.get(field) or 0.0
        pending = self.search([('product_id', '=', product.id), ('state', '=', 'pending')], limit=1)
        if pending:
            pending.write(data)
            return pending
        return self.create(dict(data, product_id=product.id))

    def action_apply(self):
        """Take Open Food Facts' data as it is now."""
        for update in self:
            product = update.product_id
            product.write(json.loads(update.values_json))
            product._trigger_photo_fetch()
            update.state = 'applied'
        return {'type': 'ir.actions.act_window_close'}

    def action_dismiss(self):
        """Keep what we have; the same OFF data will not be offered again."""
        self.write({'state': 'dismissed'})
        return {'type': 'ir.actions.act_window_close'}
