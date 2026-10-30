from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

NUTRIENTS = (
    # (key in the API, product field per 100 g)
    ('calories', 'energy_kcal_100g'),
    ('protein', 'proteins_100g'),
    ('carbs', 'carbohydrates_100g'),
    ('fat', 'fat_100g'),
)


class GymRecipeCategory(models.Model):
    """A shelf for saved dishes (Soups, Breakfast, Baking...). Shared by the family: either of
    you can add, rename or remove one; the dishes in a removed category become uncategorized."""
    _name = 'gym.recipe.category'
    _description = 'Saved Food Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    recipe_ids = fields.One2many('gym.recipe', 'category_id', string='Dishes')

    @api.constrains('name')
    def _check_name_unique(self):
        for category in self:
            clash = self.search([('name', '=ilike', category.name.strip()), ('id', '!=', category.id)], limit=1)
            if clash:
                raise ValidationError(_('There is already a category called "%s".', clash.name))

    @api.model
    def get_categories(self):
        """Every category with its number of dishes, plus how many dishes have none."""
        counts = {
            row['category_id'][0]: row['category_id_count']
            for row in self.env['gym.recipe'].read_group([('category_id', '!=', False)], ['category_id'], ['category_id'])}
        return {
            'categories': [{'id': c.id, 'name': c.name, 'count': counts.get(c.id, 0)} for c in self.search([])],
            'uncategorized': self.env['gym.recipe'].search_count([('category_id', '=', False)]),
            'total': self.env['gym.recipe'].search_count([]),
        }

    @api.model
    def create_category(self, name):
        """A new category, or the existing one with that name (case does not matter)."""
        name = (name or '').strip()
        if not name:
            raise UserError(_('Give the category a name.'))
        category = self.search([('name', '=ilike', name)], limit=1) or self.create(
            {'name': name, 'sequence': (self.search([], order='sequence desc', limit=1).sequence or 0) + 10})
        return {'id': category.id, 'name': category.name}

    def rename(self, name):
        name = (name or '').strip()
        if not name:
            raise UserError(_('Give the category a name.'))
        self.write({'name': name})
        return True


class GymRecipe(models.Model):
    """A dish someone cooked ("rice with chicken in sauce"): ingredients from the Groceries
    catalog - or other recipes, e.g. crepes + a filling - with their weight, and a number of
    servings. Logged into the diary per serving."""
    _name = 'gym.recipe'
    _description = 'Saved Recipe'
    _order = 'name'

    name = fields.Char(string='Recipe Name', required=True)
    description = fields.Text()
    user_id = fields.Many2one(
        'res.users', string='Author', default=lambda self: self.env.user, required=True, index=True)
    category_id = fields.Many2one('gym.recipe.category', string='Category', ondelete='set null', index=True)
    servings = fields.Integer(string='Servings', default=1, required=True)
    # What the finished dish weighs. Cooking changes the weight (water leaves cutlets, rice drinks
    # it), and the scale at the table shows the cooked weight - so per-100 g nutrition has to be
    # worked out against that. 0 = not weighed: the ingredients' own weights are used instead.
    cooked_weight_g = fields.Float(
        string='Finished dish weight (g)',
        help='Weigh the whole pan/pot after cooking. Leave 0 to use the sum of the ingredients.')
    total_weight_g = fields.Float(compute='_compute_totals', store=True, recursive=True)
    ingredient_ids = fields.One2many('gym.recipe.ingredient', 'recipe_id', string='Ingredients')
    # Whole-recipe totals; per-serving values are these divided by `servings`.
    calories = fields.Float(compute='_compute_totals', store=True, recursive=True)
    proteins = fields.Float(compute='_compute_totals', store=True, recursive=True)
    carbs = fields.Float(compute='_compute_totals', store=True, recursive=True)
    fat = fields.Float(compute='_compute_totals', store=True, recursive=True)

    _sql_constraints = [
        ('servings_positive', 'check(servings >= 1)', 'A recipe makes at least one serving.'),
    ]

    def unlink(self):
        used = self.env['gym.recipe.ingredient'].search([('sub_recipe_id', 'in', self.ids)])
        if used:
            raise UserError(_(
                'It is an ingredient of: %s. Take it out of there first.',
                ', '.join(sorted(set(used.mapped('recipe_id.name'))))))
        return super().unlink()

    @api.depends(
        'cooked_weight_g', 'ingredient_ids.quantity_g', 'ingredient_ids.product_id.energy_kcal_100g',
        'ingredient_ids.product_id.proteins_100g', 'ingredient_ids.product_id.carbohydrates_100g',
        'ingredient_ids.product_id.fat_100g', 'ingredient_ids.sub_recipe_id.calories',
        'ingredient_ids.sub_recipe_id.proteins', 'ingredient_ids.sub_recipe_id.carbs',
        'ingredient_ids.sub_recipe_id.fat', 'ingredient_ids.sub_recipe_id.total_weight_g')
    def _compute_totals(self):
        for recipe in self:
            calories = proteins = carbs = fat = 0.0
            for line in recipe.ingredient_ids:
                per100 = line._per_100g()
                factor = line.quantity_g / 100.0
                calories += per100['calories'] * factor
                proteins += per100['protein'] * factor
                carbs += per100['carbs'] * factor
                fat += per100['fat'] * factor
            recipe.calories, recipe.proteins, recipe.carbs, recipe.fat = calories, proteins, carbs, fat
            recipe.total_weight_g = recipe.cooked_weight_g or sum(recipe.ingredient_ids.mapped('quantity_g'))

    def _per_serving(self):
        self.ensure_one()
        n = max(self.servings, 1)
        return {
            'calories': self.calories / n, 'protein': self.proteins / n,
            'carbs': self.carbs / n, 'fat': self.fat / n,
        }

    def _serving_weight(self):
        """Grams in one serving (the finished dish split evenly)."""
        self.ensure_one()
        return (self.total_weight_g or 0.0) / max(self.servings, 1)

    def _per_100g(self):
        """Nutrition of 100 g of the finished dish - what grams eaten are multiplied by."""
        self.ensure_one()
        weight = self.total_weight_g
        factor = 100.0 / weight if weight else 0.0
        return {
            'calories': self.calories * factor, 'protein': self.proteins * factor,
            'carbs': self.carbs * factor, 'fat': self.fat * factor,
        }

    # ------------------------------------------------------------------ API for the Meals UI

    def _card(self):
        self.ensure_one()
        per = self._per_serving()
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'category_id': self.category_id.id,
            'category': self.category_id.name or '',
            'servings': self.servings,
            'per_serving': {key: round(value, 1) for key, value in per.items()},
            'per_100g': {key: round(value, 1) for key, value in self._per_100g().items()},
            'total_weight_g': round(self.total_weight_g, 1),
            'serving_weight_g': round(self._serving_weight(), 1),
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
    def set_category(self, recipe_id, category_id):
        """File a dish under a category. Anyone of the family can do it, also for the other's
        dishes: the category is a label for finding it, not a change of the recipe itself."""
        category = self.env['gym.recipe.category'].browse(category_id).exists() if category_id else False
        self.sudo().browse(recipe_id).exists().write({'category_id': category.id if category else False})
        return True

    @api.model
    def get_recipe(self, recipe_id):
        recipe = self.browse(recipe_id).exists()
        if not recipe:
            raise UserError(_('This recipe no longer exists.'))
        data = recipe._card()
        data['cooked_weight_g'] = recipe.cooked_weight_g
        data['raw_weight_g'] = round(sum(recipe.ingredient_ids.mapped('quantity_g')), 1)
        data['ingredients'] = [{
            'product_id': line.product_id.id,
            'sub_recipe_id': line.sub_recipe_id.id,
            'name': line.product_id.name or line.sub_recipe_id.name,
            'quantity_g': line.quantity_g,
            'per100': line._per_100g(),
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
        cooked = float(data.get('cooked_weight_g') or 0)
        if cooked < 0:
            raise UserError(_('The weight of the dish cannot be negative.'))
        lines = [
            (0, 0, {
                'product_id': int(line['product_id']) if line.get('product_id') else False,
                'sub_recipe_id': int(line['sub_recipe_id']) if line.get('sub_recipe_id') else False,
                'quantity_g': float(line['quantity_g']),
            })
            for line in data.get('ingredients') or []
        ]
        if not lines:
            raise UserError(_('Add at least one ingredient.'))
        vals = {
            'name': name,
            'category_id': int(data['category_id']) if data.get('category_id') else False,
            'description': (data.get('description') or '').strip() or False,
            'servings': servings,
            'cooked_weight_g': cooked,
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
    # An ingredient is a Groceries product OR another recipe (crepes + their filling), by weight.
    product_id = fields.Many2one('groceries.product', string='Food', ondelete='cascade')
    sub_recipe_id = fields.Many2one(
        'gym.recipe', string='Recipe as ingredient', ondelete='restrict', index=True)
    quantity_g = fields.Float(string='Weight (g/ml)', default=100.0)

    _sql_constraints = [
        ('quantity_positive', 'check(quantity_g > 0)', 'An ingredient needs a weight above zero.'),
        ('one_source', 'check((product_id is null) != (sub_recipe_id is null))',
         'An ingredient is either a food or a recipe.'),
    ]

    @api.constrains('sub_recipe_id', 'recipe_id')
    def _check_no_cycle(self):
        """A recipe cannot contain itself, not even through other recipes."""
        for line in self:
            todo, seen = line.sub_recipe_id, set()
            while todo:
                if line.recipe_id in todo:
                    raise ValidationError(_(
                        '%s cannot be an ingredient of itself (even through another recipe).',
                        line.recipe_id.name))
                seen |= set(todo.ids)
                todo = todo.ingredient_ids.sub_recipe_id.filtered(lambda r: r.id not in seen)

    def _per_100g(self):
        """Nutrition of 100 g of this ingredient: the product's, or the finished sub-recipe's."""
        self.ensure_one()
        if self.sub_recipe_id:
            return self.sub_recipe_id._per_100g()
        return {key: self.product_id[field] for key, field in NUTRIENTS}
