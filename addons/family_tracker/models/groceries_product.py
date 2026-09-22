import base64
import logging
from html import escape

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Open Food Facts asks integrators to identify themselves with a descriptive
# User-Agent instead of a generic library default (their API is free but rate-limited).
OFF_USER_AGENT = 'FamilyDailyTracker/1.0 (family-tracker@example.com)'
OFF_API_URL = 'https://world.openfoodfacts.org/api/v2/product/{barcode}.json'
# Restrict the response to what we actually use - the full OFF payload has 100+ keys.
OFF_FIELDS = (
    'product_name,generic_name,categories_tags,image_front_url,image_url,image_front_small_url,'
    'nutriscore_grade,nutriscore_data,nutriments'
)

# Official Nutri-Score colors (A = best, E = worst), used for the badge in the form view.
NUTRISCORE_COLORS = {
    'a': '#038141',
    'b': '#85BB2F',
    'c': '#FECB02',
    'd': '#EE8100',
    'e': '#E63E11',
}

NUTRISCORE_COMPONENT_LABELS = {
    'energy': 'Energy',
    'sugars': 'Sugars',
    'saturated_fat': 'Saturated Fat',
    'salt': 'Salt',
    'sodium': 'Sodium',
    'fiber': 'Fiber',
    'fruits_vegetables_legumes': 'Fruits & Vegetables',
    'proteins': 'Proteins',
}


class GroceriesProduct(models.Model):
    _name = 'groceries.product'
    _description = 'Groceries Product (Catalog)'
    _order = 'name'

    name = fields.Char(string='Product Name', required=True)
    # Barcode identifies the product *type* (e.g. "Milk 1L Łaciate"), not a single
    # physical pack. Scanning the same barcode twice should find this same record.
    barcode = fields.Char(string='Barcode (EAN-13)', index=True, copy=False)
    image = fields.Image(string='Photo', max_width=512, max_height=512)
    # Photo URL from Open Food Facts that still has to be downloaded. Set on scan,
    # cleared by the background cron once the image is stored (see _cron_fetch_missing_images).
    off_image_url = fields.Char(string='Pending OFF Photo URL', copy=False)
    # URL of the OFF photo that is currently stored as `image`. Empty when the photo was
    # uploaded by hand (or there is none) - a refresh must not replace those.
    off_image_source_url = fields.Char(string='Stored OFF Photo URL', copy=False)

    # Open Food Facts categories are a hierarchy, not a fixed list (e.g. a sauce is
    # tagged Condiments + Sauces + Worcestershire Sauces), so this is a many2many
    # to an open tag vocabulary instead of a Selection.
    category_ids = fields.Many2many('groceries.product.category', string='Categories')

    default_uom_id = fields.Many2one(
        'uom.uom', string='Default Unit of Measure',
        help='Unit new stock entries for this product will default to (e.g. Liter for milk).')

    is_essential = fields.Boolean(
        string='Essential Product', default=False,
        help='Check if this product must always be restocked (e.g. bread, milk).')
    min_quantity = fields.Float(
        string='Minimum Required Quantity', default=1.0,
        help='When total in-stock quantity drops below this, it qualifies for auto reorder.')
    auto_reorder = fields.Boolean(
        string='Auto Add to Shopping List', default=True,
        help='Automatically create a "To Buy" stock entry when stock runs low.')

    nutriscore_grade = fields.Selection([
        ('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D'), ('e', 'E'),
    ], string='Nutri-Score')
    nutriscore_negative_points = fields.Integer(string='Nutri-Score Negative Points')
    nutriscore_negative_points_max = fields.Integer(string='Nutri-Score Negative Points (Max)')
    nutriscore_positive_points = fields.Integer(string='Nutri-Score Positive Points')
    nutriscore_positive_points_max = fields.Integer(string='Nutri-Score Positive Points (Max)')
    nutriscore_breakdown = fields.Html(string='Nutri-Score Breakdown', sanitize=False)

    energy_kcal_100g = fields.Float(string='Energy (kcal/100g)')
    energy_kj_100g = fields.Float(string='Energy (kJ/100g)')
    fat_100g = fields.Float(string='Fat (g/100g)')
    saturated_fat_100g = fields.Float(string='Saturated Fat (g/100g)')
    carbohydrates_100g = fields.Float(string='Carbohydrates (g/100g)')
    sugars_100g = fields.Float(string='Sugars (g/100g)')
    fiber_100g = fields.Float(string='Fiber (g/100g)')
    proteins_100g = fields.Float(string='Proteins (g/100g)')
    salt_100g = fields.Float(string='Salt (g/100g)')
    sodium_100g = fields.Float(string='Sodium (g/100g)')
    fruits_vegetables_100g = fields.Float(string='Fruits/Vegetables/Legumes (%)')

    stock_entry_ids = fields.One2many('groceries.stock_entry', 'product_id', string='Stock Entries')
    stock_quantity = fields.Float(
        string='Current Stock', compute='_compute_stock_quantity', store=True,
        help='Sum of quantity across all stock entries currently "In Stock".')
    stock_entry_count = fields.Integer(string='Stock Entry Count', compute='_compute_stock_entry_count')
    is_low_stock = fields.Boolean(
        string='Low Stock', compute='_compute_is_low_stock', store=True,
        help='Stock quantity has dropped below the minimum required quantity.')

    _sql_constraints = [
        ('barcode_uniq', 'unique(barcode)', 'A product with this barcode already exists.'),
    ]

    def write(self, vals):
        if 'image' in vals and not self.env.context.get('off_photo_sync') \
                and 'off_image_source_url' not in vals:
            vals = dict(vals, off_image_source_url=False)
        return super().write(vals)

    @api.depends('stock_entry_ids.state', 'stock_entry_ids.quantity')
    def _compute_stock_quantity(self):
        for product in self:
            in_stock_entries = product.stock_entry_ids.filtered(lambda e: e.state == 'in_stock')
            product.stock_quantity = sum(in_stock_entries.mapped('quantity'))

    @api.depends('stock_entry_ids')
    def _compute_stock_entry_count(self):
        for product in self:
            product.stock_entry_count = len(product.stock_entry_ids)

    @api.depends('stock_quantity', 'min_quantity')
    def _compute_is_low_stock(self):
        for product in self:
            product.is_low_stock = product.stock_quantity < product.min_quantity

    @api.model
    def create_from_barcode(self, barcode):
        """Return (product, created) for a barcode: the existing catalog entry,
        or a new one pre-filled from Open Food Facts when we've never seen it."""
        product = self.search([('barcode', '=', barcode)], limit=1)
        if product:
            # Placeholder from an earlier scan that Open Food Facts didn't know about
            # yet (name still equals the raw barcode) - retry now, someone may have
            # added it there since.
            if product.name == barcode:
                product._refresh_from_off()
            return product, False

        vals = {'barcode': barcode, 'name': barcode}
        off_vals = self._fetch_off_product(barcode)
        if off_vals:
            vals.update(off_vals)
        product = self.create(vals)
        product._trigger_photo_fetch()
        return product, True

    def _trigger_photo_fetch(self):
        if any(self.mapped('off_image_url')):
            self.env.ref('family_tracker.ir_cron_fetch_product_images').sudo()._trigger()

    def _refresh_from_off(self, raise_on_error=False):
        """Re-read this product from Open Food Facts. Returns True if OFF knew the barcode.
        Never overwrites what a person did by hand: a real name stays, and a photo
        uploaded manually is kept."""
        self.ensure_one()
        vals = self._fetch_off_product(self.barcode, raise_on_error=raise_on_error)
        if not vals:
            return False
        if self.name != self.barcode or vals.get('name') == self.barcode:
            vals.pop('name', None)
        # A photo that came from OFF is replaced when OFF now shows a different one (its URL
        # changes with every new revision); a photo uploaded by hand is never touched.
        image_url = vals.get('off_image_url')
        if image_url and self.image and (
                not self.off_image_source_url or self.off_image_source_url == image_url):
            vals.pop('off_image_url')
        self.write(vals)
        self._trigger_photo_fetch()
        return True

    def action_refresh_from_off(self):
        self.ensure_one()
        try:
            found = self._refresh_from_off(raise_on_error=True)
        except requests.RequestException:
            raise UserError(_('Open Food Facts could not be reached. Please try again in a minute.'))
        if found:
            title, kind = _('Updated from Open Food Facts'), 'success'
            message = _('Data refreshed. A missing photo, if any, will appear in a few seconds.')
        else:
            title, kind = _('Not on Open Food Facts yet'), 'warning'
            message = _('No product with barcode %s was found there. Add it on openfoodfacts.org, then try again.') % self.barcode
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title, 'message': message, 'type': kind, 'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_refresh_from_off_bulk(self):
        found = missing = failed = 0
        for product in self.filtered('barcode'):
            try:
                if product._refresh_from_off(raise_on_error=True):
                    found += 1
                else:
                    missing += 1
            except requests.RequestException:
                failed += 1
        message = _('%(found)s updated, %(missing)s not on Open Food Facts yet, %(failed)s failed.',
                    found=found, missing=missing, failed=failed)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Refresh from Open Food Facts'), 'message': message,
                'type': 'warning' if failed else 'success', 'sticky': bool(failed),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    @api.model
    def _cron_refresh_unresolved_products(self):
        """Nightly: ask Open Food Facts again about products still named after their barcode
        (scanned before anyone added them there)."""
        products = self.search([('barcode', '!=', False)]).filtered(lambda p: p.name == p.barcode)
        for product in products[:100]:
            if product._refresh_from_off():
                self.env.cr.commit()

    def _fetch_off_product(self, barcode, raise_on_error=False):
        """Look up a barcode on Open Food Facts. Returns a dict of field values
        to pre-fill the product with, or None if the product isn't listed there
        (common for local Polish brands) or the API is unreachable (unless
        raise_on_error, which lets a caller tell those two cases apart)."""
        try:
            response = requests.get(
                OFF_API_URL.format(barcode=barcode),
                params={'fields': OFF_FIELDS},
                headers={'User-Agent': OFF_USER_AGENT},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            if raise_on_error:
                raise
            _logger.warning('Open Food Facts lookup failed for barcode %s', barcode, exc_info=True)
            return None

        # status == 0 means "barcode not found in their database", not an HTTP error.
        if payload.get('status') != 1:
            return None

        off_product = payload['product']
        vals = {'name': off_product.get('product_name') or off_product.get('generic_name') or barcode}

        category_tags = off_product.get('categories_tags') or []
        if category_tags:
            categories = self.env['groceries.product.category']._get_or_create_from_off_tags(category_tags)
            vals['category_ids'] = [(6, 0, categories.ids)]

        # Only remember the largest variant OFF's API guarantees (~400px); the download
        # itself happens in the background - images.openfoodfacts.org can take 10-20s just
        # to finish its TLS handshake, which used to block the scan response.
        image_url = (
            off_product.get('image_front_url')
            or off_product.get('image_url')
            or off_product.get('image_front_small_url')
        )
        if image_url:
            vals['off_image_url'] = image_url

        nutriments = off_product.get('nutriments')
        if nutriments:
            vals.update(self._map_off_nutrition(nutriments))
        vals.update(self._map_off_nutriscore(
            off_product.get('nutriscore_grade'), off_product.get('nutriscore_data') or {}))

        return vals

    @api.model
    def _map_off_nutrition(self, nutriments):
        def value(key):
            raw = nutriments.get(key)
            return float(raw) if raw is not None else 0.0

        return {
            'energy_kcal_100g': value('energy-kcal_100g'),
            'energy_kj_100g': value('energy-kj_100g'),
            'fat_100g': value('fat_100g'),
            'saturated_fat_100g': value('saturated-fat_100g'),
            'carbohydrates_100g': value('carbohydrates_100g'),
            'sugars_100g': value('sugars_100g'),
            'fiber_100g': value('fiber_100g'),
            'proteins_100g': value('proteins_100g'),
            'salt_100g': value('salt_100g'),
            'sodium_100g': value('sodium_100g'),
            'fruits_vegetables_100g': value('fruits-vegetables-legumes-estimate-from-ingredients_100g'),
        }

    @api.model
    def _map_off_nutriscore(self, grade, nutriscore_data):
        vals = {}
        if grade in dict(self._fields['nutriscore_grade'].selection):
            vals['nutriscore_grade'] = grade
        if nutriscore_data:
            vals['nutriscore_negative_points'] = nutriscore_data.get('negative_points') or 0
            vals['nutriscore_negative_points_max'] = nutriscore_data.get('negative_points_max') or 0
            vals['nutriscore_positive_points'] = nutriscore_data.get('positive_points') or 0
            vals['nutriscore_positive_points_max'] = nutriscore_data.get('positive_points_max') or 0
            vals['nutriscore_breakdown'] = self._build_nutriscore_breakdown_html(nutriscore_data)
        return vals

    @api.model
    def _build_nutriscore_breakdown_html(self, nutriscore_data):
        components = nutriscore_data.get('components') or {}

        def render_rows(items):
            rows = []
            for item in items:
                label = NUTRISCORE_COMPONENT_LABELS.get(
                    item.get('id'), (item.get('id') or '').replace('_', ' ').title())
                rows.append(
                    '<tr><td>%s</td><td>%s/%s pts</td><td>%s %s</td></tr>' % (
                        escape(label),
                        escape(str(item.get('points', 0))),
                        escape(str(item.get('points_max', 0))),
                        escape(str(item.get('value', ''))),
                        escape(item.get('unit') or ''),
                    )
                )
            return ''.join(rows)

        return (
            '<div class="o_groceries_nutriscore_breakdown">'
            '<table class="table table-sm"><thead><tr><th colspan="3">Negative points: %s/%s</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<table class="table table-sm"><thead><tr><th colspan="3">Positive points: %s/%s</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '</div>' % (
                nutriscore_data.get('negative_points', 0),
                nutriscore_data.get('negative_points_max', 0),
                render_rows(components.get('negative') or []),
                nutriscore_data.get('positive_points', 0),
                nutriscore_data.get('positive_points_max', 0),
                render_rows(components.get('positive') or []),
            )
        )

    @api.model
    def _cron_fetch_missing_images(self):
        """Download photos queued via off_image_url. Failures keep the URL so the next
        (triggered or scheduled) run retries."""
        for product in self.search([('off_image_url', '!=', False)], limit=10):
            url = product.off_image_url
            image = self._download_image(url)
            if image:
                product.with_context(off_photo_sync=True).write({
                    'image': image, 'off_image_url': False, 'off_image_source_url': url})
                self.env.cr.commit()

    @api.model
    def _download_image(self, url):
        # OFF's image server is much slower than its product-data API (TLS handshake alone
        # often 8-20s); nobody is waiting on this now, so allow it plenty of time.
        try:
            response = requests.get(url, headers={'User-Agent': OFF_USER_AGENT}, timeout=60)
            response.raise_for_status()
        except requests.RequestException:
            _logger.warning('Failed to download product image from %s', url, exc_info=True)
            return False
        return base64.b64encode(response.content)

    def action_view_stock_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock Entries',
            'res_model': 'groceries.stock_entry',
            'view_mode': 'list,form',
            'domain': [('product_id', '=', self.id)],
            'context': {'default_product_id': self.id},
        }
