from odoo import _, api, fields, models
from odoo.exceptions import UserError

NUTRIENTS = (
    # (key in the API, product field per 100 g)
    ('calories', 'energy_kcal_100g'),
    ('protein', 'proteins_100g'),
    ('carbs', 'carbohydrates_100g'),
    ('fat', 'fat_100g'),
)


class GymRecipe(models.Model):
    """A dish someone cooked ("rice with chicken in sauce"): ingredients from the Groceries
    catalog with their weight, and a number of servings. Logged into the diary per serving."""
    _name = 'gym.recipe'
    _description = 'Saved Recipe'
    _order = 'name'

    name = fields.Char(string='Recipe Name', required=True)
    description = fields.Text()
    user_id = fields.Many2one(
        'res.users', string='Author', default=lambda self: self.env.user, required=True, index=True)
    servings = fields.Integer(string='Servings', default=1, required=True)
    ingredient_ids = fields.One2many('gym.recipe.ingredient', 'recipe_id', string='Ingredients')
    # Whole-recipe totals; per-serving values are these divided by `servings`.
    calories = fields.Float(compute='_compute_totals', store=True)
    proteins = fields.Float(compute='_compute_totals', store=True)
    carbs = fields.Float(compute='_compute_totals', store=True)
    fat = fields.Float(compute='_compute_totals', store=True)

    _sql_constraints = [
        ('servings_positive', 'check(servings >= 1)', 'A recipe makes at least one serving.'),
    ]

    @api.depends(
        'ingredient_ids.quantity_g', 'ingredient_ids.product_id.energy_kcal_100g',
        'ingredient_ids.product_id.proteins_100g', 'ingredient_ids.product_id.carbohydrates_100g',
        'ingredient_ids.product_id.fat_100g')
    def _compute_totals(self):
        for recipe in self:
            calories = proteins = carbs = fat = 0.0
            for line in recipe.ingredient_ids:
                factor = line.quantity_g / 100.0
                product = line.product_id
                calories += product.energy_kcal_100g * factor
                proteins += product.proteins_100g * factor
                carbs += product.carbohydrates_100g * factor
                fat += product.fat_100g * factor
            recipe.calories, recipe.proteins, recipe.carbs, recipe.fat = calories, proteins, carbs, fat

    def _per_serving(self):
        self.ensure_one()
        n = max(self.servings, 1)
        return {
            'calories': self.calories / n, 'protein': self.proteins / n,
            'carbs': self.carbs / n, 'fat': self.fat / n,
        }

    # ------------------------------------------------------------------ API for the Meals UI

    def _card(self):
        self.ensure_one()
        per = self._per_serving()
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'servings': self.servings,
            'per_serving': {key: round(value, 1) for key, value in per.items()},
            'ingredient_count': len(self.ingredient_ids),
            'owner': self.user_id.name,
            'mine': self.user_id == self.env.user,
        }

    @api.model
    def get_saved(self, search=''):
        """Saved recipes of the family (everyone can read all; only the author edits), the
        current user's own first."""
        domain = [('name', 'ilike', search)] if search else []
        recipes = self.search(domain).sorted(
            key=lambda r: (r.user_id != self.env.user, (r.name or '').lower()))
        return [recipe._card() for recipe in recipes]

    @api.model
    def get_recipe(self, recipe_id):
        recipe = self.browse(recipe_id).exists()
        if not recipe:
            raise UserError(_('This recipe no longer exists.'))
        data = recipe._card()
        data['ingredients'] = [{
            'product_id': line.product_id.id,
            'name': line.product_id.name,
            'quantity_g': line.quantity_g,
            'per100': {key: line.product_id[field] for key, field in NUTRIENTS},
        } for line in recipe.ingredient_ids]
        return data

    @api.model
    def save_recipe(self, data):
        """Create (no `id`) or update a recipe from the form; ingredients are replaced as a
        whole. Returns the saved recipe as get_recipe() does."""
        name = (data.get('name') or '').strip()
        if not name:
            raise UserError(_('Give the recipe a name.'))
        servings = int(data.get('servings') or 0)
        if servings < 1:
            raise UserError(_('A recipe makes at least one serving.'))
        lines = [
            (0, 0, {'product_id': int(line['product_id']), 'quantity_g': float(line['quantity_g'])})
            for line in data.get('ingredients') or []
        ]
        if not lines:
            raise UserError(_('Add at least one ingredient.'))
        vals = {
            'name': name,
            'description': (data.get('description') or '').strip() or False,
            'servings': servings,
            'ingredient_ids': [(5, 0, 0)] + lines,
        }
        if data.get('id'):
            recipe = self.browse(data['id'])
            recipe.write(vals)
        else:
            recipe = self.create(vals)
        return self.get_recipe(recipe.id)


class GymRecipeIngredient(models.Model):
    _name = 'gym.recipe.ingredient'
    _description = 'Recipe Ingredient'
    _order = 'sequence, id'

    recipe_id = fields.Many2one('gym.recipe', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'groceries.product', string='Food', required=True, ondelete='restrict')
    quantity_g = fields.Float(string='Weight (g/ml)', default=100.0)

    _sql_constraints = [
        ('quantity_positive', 'check(quantity_g > 0)', 'An ingredient needs a weight above zero.'),
    ]
