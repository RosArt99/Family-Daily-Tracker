def migrate(cr, version):
    """Recipe entries used to be logged by servings only, so their grams (quantity_g) just
    carried the unrelated default of 100. Give them the real amount: servings eaten x the weight
    of one serving at the time of the upgrade.

    Plain SQL on purpose: writing quantity_g through the ORM would recompute the entry's
    calories from the recipe as it is today and rewrite past days."""
    cr.execute("""
        UPDATE gym_meal_log m
           SET quantity_g = m.servings * r.total_weight_g / GREATEST(r.servings, 1)
          FROM gym_recipe r
         WHERE m.recipe_id = r.id AND r.total_weight_g > 0
    """)
