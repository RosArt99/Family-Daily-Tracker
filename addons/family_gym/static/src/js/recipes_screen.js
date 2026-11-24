/** @odoo-module **/

import { onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { AddFoodDialog } from "./meals_recipes";

// Recipes as an app of their own (a Home tile): the family's dishes one tap away - browse by
// category, search, add or edit one, and tap a dish to put it into today's diary. It is the
// "My Saved Food" list of the Meals diary (same methods, same cards), just not three dialogs deep.
export class RecipesScreen extends AddFoodDialog {
    static template = "family_gym.RecipesScreen";
    static components = {};
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            search: "",
            recipes: [],
            category: "all",
            categories: [],
            uncategorized: 0,
            total: 0,
        });
        this.searchDebounced = useDebounced(() => this.loadRecipes(), 250);
        onWillStart(() => this.loadRecipes());
    }

    // Tap a dish: how much, which meal, whose diary - then it is in today's diary.
    pick(recipe) {
        this.dialog.add(AddFoodDialog, {
            recipeId: recipe.id,
            grams: Math.round(recipe.serving_weight_g) || 100,
            onDone: () => this.notification.add(_t("%s is in the diary", recipe.name), { type: "success" }),
        });
    }
}

registry.category("actions").add("family_gym.recipes", RecipesScreen);
