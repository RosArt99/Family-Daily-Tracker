from odoo import _, api, fields, models
from odoo.exceptions import UserError

MENU_CATEGORIES = [
    ('menu', 'Menu / meals'),
    ('burger', 'Burgers'),
    ('chicken', 'Chicken'),
    ('wrap', 'Wraps & rolls'),
    ('sandwich', 'Sandwiches'),
    ('kebab', 'Kebab'),
    ('side', 'Sides'),
    ('drink', 'Drinks'),
    ('dessert', 'Desserts'),
]


class GymRestaurant(models.Model):
    """A fast-food place you can pick from when logging a meal. Values are for the Polish menu
    (they differ between countries: local recipes and local menu items)."""
    _name = 'gym.restaurant'
    _description = 'Restaurant'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    logo = fields.Image(max_width=256, max_height=256)
    item_ids = fields.One2many('gym.restaurant.item', 'restaurant_id', string='Menu')
    item_count = fields.Integer(compute='_compute_item_count')

    @api.depends('item_ids')
    def _compute_item_count(self):
        for restaurant in self:
            restaurant.item_count = len(restaurant.item_ids)

    @api.model
    def get_restaurants(self):
        return [{'id': r.id, 'name': r.name, 'count': r.item_count} for r in self.search([])]

    @api.model
    def get_menu(self, restaurant_id):
        restaurant = self.browse(restaurant_id).exists()
        if not restaurant:
            raise UserError(_('This restaurant no longer exists.'))
        labels = dict(MENU_CATEGORIES)
        return {
            'id': restaurant.id,
            'name': restaurant.name,
            'items': [item._card() for item in restaurant.item_ids],
            'categories': [
                {'key': key, 'label': labels[key]} for key in labels
                if restaurant.item_ids.filtered(lambda i, k=key: i.category == k)],
        }


class GymRestaurantItem(models.Model):
    _name = 'gym.restaurant.item'
    _description = 'Restaurant Menu Item'
    _order = 'restaurant_id, sequence, id'

    restaurant_id = fields.Many2one('gym.restaurant', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    category = fields.Selection(MENU_CATEGORIES, default='burger', required=True)
    serving_g = fields.Float(string='Weight (g)', help='0 when the menu does not say.')
    calories = fields.Float(string='kcal')
    proteins = fields.Float(string='Protein (g)')
    carbs = fields.Float(string='Carbs (g)')
    fat = fields.Float(string='Fat (g)')
    # True for combos (burger + fries + drink, worked out by adding the parts up) and for typical
    # values of a dish the chain does not publish: shown with a "~" in the app.
    is_estimate = fields.Boolean(string='Estimate')
    note = fields.Char(help='e.g. what a menu combo contains.')

    def _card(self):
        self.ensure_one()
        return {
            'id': self.id, 'name': self.name, 'category': self.category,
            'serving_g': self.serving_g, 'calories': self.calories, 'protein': self.proteins,
            'carbs': self.carbs, 'fat': self.fat, 'estimate': self.is_estimate,
            'note': self.note or '', 'restaurant_id': self.restaurant_id.id,
            'restaurant': self.restaurant_id.name,
        }

    @api.model
    def get_item(self, item_id):
        item = self.browse(item_id).exists()
        if not item:
            raise UserError(_('This menu item no longer exists.'))
        return item._card()
