from odoo import api, fields, models


class GroceriesProductCategory(models.Model):
    _name = 'groceries.product.category'
    _description = 'Groceries Product Category (Open Food Facts)'
    _order = 'name'

    name = fields.Char(required=True)
    # e.g. "en:worcestershire-sauces" - Open Food Facts' stable tag id for this
    # category, used to find-or-create instead of matching on the display name.
    off_tag = fields.Char(string='Open Food Facts Tag', index=True, copy=False)

    _sql_constraints = [
        ('off_tag_uniq', 'unique(off_tag)', 'This Open Food Facts category already exists.'),
    ]

    @api.model
    def _get_or_create_from_off_tags(self, off_tags):
        categories = self.browse()
        for tag in off_tags:
            category = self.search([('off_tag', '=', tag)], limit=1)
            if not category:
                label = tag.split(':', 1)[-1].replace('-', ' ').title()
                category = self.create({'name': label, 'off_tag': tag})
            categories |= category
        return categories
