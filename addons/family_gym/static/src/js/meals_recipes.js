/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

// Colours of the three macros, shared by the split bar and its legend.
const MACRO_COLORS = { protein: "#1e88e5", carbs: "#f0a30a", fat: "#ef7b5d" };
const KCAL_PER_GRAM = { protein: 4, carbs: 4, fat: 9 };

// Accepts "12", "12.5" or "12,5" (phone keyboards); anything else counts as 0.
function num(value) {
    const n = parseFloat(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}

function fmt(value) {
    return Math.round(value);
}

// The recipe form. Same look as the Meals diary (white rounded cards on a light background),
// with a coloured header for the name, a big servings stepper and a live nutrition summary.
export class RecipeFormDialog extends Component {
    static template = "family_gym.RecipeFormDialog";
    static components = { Dialog };
    static props = {
        recipeId: { type: Number, optional: true },
        onSaved: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.nextKey = 1;
        this.state = useState({
            name: "",
            description: "",
            servings: "1",
            ingredients: [],
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            if (this.props.recipeId) {
                const recipe = await this.orm.call("gym.recipe", "get_recipe", [this.props.recipeId]);
                this.state.name = recipe.name;
                this.state.description = recipe.description;
                this.state.servings = String(recipe.servings);
                this.state.ingredients = recipe.ingredients.map((line) =>
                    this.makeIngredient(line.product_id, line.name, line.quantity_g, line.per100)
                );
            }
        });
    }

    get title() {
        return this.props.recipeId ? _t("Edit recipe") : _t("New recipe");
    }

    makeIngredient(productId, name, quantity, per100) {
        return {
            key: this.nextKey++,
            product_id: productId,
            name,
            quantity: String(quantity),
            per100,
            // Products without nutrition data would silently count as 0 kcal.
            missing: !Object.values(per100).some((value) => value > 0),
        };
    }

    // ---- servings (digits only) ----
    get servingsCount() {
        return Math.max(1, parseInt(this.state.servings, 10) || 1);
    }

    onServingsInput(ev) {
        const digits = ev.target.value.replace(/\D/g, "");
        ev.target.value = digits;
        this.state.servings = digits;
    }

    onServingsBlur() {
        this.state.servings = String(this.servingsCount);
    }

    stepServings(delta) {
        this.state.servings = String(Math.max(1, this.servingsCount + delta));
    }

    // ---- ingredients ----
    addIngredients() {
        this.dialog.add(SelectCreateDialog, {
            title: _t("Add ingredients"),
            resModel: "groceries.product",
            multiSelect: true,
            noCreate: true,
            // Start from what is in the pantry; remove the filter to search the whole catalog.
            context: { search_default_filter_in_stock: 1 },
            onSelected: async (ids) => {
                const known = new Set(this.state.ingredients.map((line) => line.product_id));
                const products = await this.orm.read("groceries.product", ids.filter((id) => !known.has(id)), [
                    "name",
                    "energy_kcal_100g",
                    "proteins_100g",
                    "carbohydrates_100g",
                    "fat_100g",
                ]);
                for (const product of products) {
                    this.state.ingredients.push(
                        this.makeIngredient(product.id, product.name, 100, {
                            calories: product.energy_kcal_100g,
                            protein: product.proteins_100g,
                            carbs: product.carbohydrates_100g,
                            fat: product.fat_100g,
                        })
                    );
                }
            },
        });
    }

    removeIngredient(line) {
        this.state.ingredients = this.state.ingredients.filter((other) => other !== line);
    }

    onWeightInput(ev, line) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        line.quantity = cleaned;
    }

    lineKcal(line) {
        return fmt((line.per100.calories * num(line.quantity)) / 100);
    }

    // ---- live nutrition ----
    get totals() {
        const total = { calories: 0, protein: 0, carbs: 0, fat: 0, weight: 0 };
        for (const line of this.state.ingredients) {
            const grams = num(line.quantity);
            total.weight += grams;
            for (const key of ["calories", "protein", "carbs", "fat"]) {
                total[key] += (line.per100[key] * grams) / 100;
            }
        }
        return total;
    }

    get perServing() {
        const total = this.totals;
        const n = this.servingsCount;
        return {
            calories: fmt(total.calories / n),
            protein: fmt(total.protein / n),
            carbs: fmt(total.carbs / n),
            fat: fmt(total.fat / n),
        };
    }

    get macroSplit() {
        const per = this.perServing;
        const kcal = Object.keys(KCAL_PER_GRAM).map((key) => ({
            key,
            value: per[key] * KCAL_PER_GRAM[key],
        }));
        const sum = kcal.reduce((acc, item) => acc + item.value, 0);
        return Object.keys(KCAL_PER_GRAM).map((key, index) => ({
            key,
            label: { protein: _t("Protein"), carbs: _t("Carbs"), fat: _t("Fat") }[key],
            grams: per[key],
            color: MACRO_COLORS[key],
            percent: sum ? (kcal[index].value / sum) * 100 : 0,
        }));
    }

    fmt(value) {
        return fmt(value);
    }

    // ---- save ----
    async save() {
        const { state } = this;
        state.error = "";
        if (!state.name.trim()) {
            state.error = _t("Give the recipe a name.");
            return;
        }
        if (!state.ingredients.length) {
            state.error = _t("Add at least one ingredient.");
            return;
        }
        if (state.ingredients.some((line) => num(line.quantity) <= 0)) {
            state.error = _t("Every ingredient needs a weight above zero.");
            return;
        }
        state.saving = true;
        try {
            const recipe = await this.orm.call("gym.recipe", "save_recipe", [
                {
                    id: this.props.recipeId || false,
                    name: state.name,
                    description: state.description,
                    servings: this.servingsCount,
                    ingredients: state.ingredients.map((line) => ({
                        product_id: line.product_id,
                        quantity_g: num(line.quantity),
                    })),
                },
            ]);
            if (this.props.onSaved) {
                this.props.onSaved(recipe);
            }
            this.props.close();
        } finally {
            state.saving = false;
        }
    }
}

// What the "+" of a meal opens: choose where the food comes from. "My Saved Food" lists the
// recipes (with "Add New Recipe"), and tapping one asks how many servings you ate.
export class AddFoodDialog extends Component {
    static template = "family_gym.AddFoodDialog";
    static components = { Dialog };
    static props = {
        meal: { type: String, optional: true },
        mealLabel: { type: String, optional: true },
        date: { type: String, optional: true },
        // Editing the servings of a recipe entry that is already in the diary.
        entry: { type: Object, optional: true },
        onPantry: { type: Function, optional: true },
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            step: this.props.entry ? "servings" : "menu",
            search: "",
            recipes: [],
            recipe: null,
            servings: this.props.entry ? String(this.props.entry.servings) : "1",
            busy: false,
        });
        this.searchDebounced = useDebounced(() => this.loadRecipes(), 250);
        onWillStart(async () => {
            if (this.props.entry) {
                this.state.recipe = await this.orm.call("gym.recipe", "get_recipe", [
                    this.props.entry.recipe_id,
                ]);
            }
        });
    }

    get title() {
        if (this.state.step === "saved") {
            return _t("My Saved Food");
        }
        if (this.state.step === "servings") {
            return this.state.recipe.name;
        }
        return _t("Add to %s", this.props.mealLabel || _t("diary"));
    }

    fmt(value) {
        return fmt(value);
    }

    // ---- navigation ----
    back() {
        this.state.step = this.state.step === "servings" ? "saved" : "menu";
    }

    pantry() {
        this.props.close();
        this.props.onPantry();
    }

    async openSaved() {
        this.state.step = "saved";
        await this.loadRecipes();
    }

    // ---- saved recipes ----
    async loadRecipes() {
        this.state.recipes = await this.orm.call("gym.recipe", "get_saved", [this.state.search]);
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.searchDebounced();
    }

    newRecipe() {
        this.dialog.add(RecipeFormDialog, { onSaved: () => this.loadRecipes() });
    }

    editRecipe(recipe) {
        this.dialog.add(RecipeFormDialog, { recipeId: recipe.id, onSaved: () => this.loadRecipes() });
    }

    deleteRecipe(recipe) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete recipe"),
            body: _t("Delete %s? Days you already logged it in keep their calories.", recipe.name),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.unlink("gym.recipe", [recipe.id]);
                await this.loadRecipes();
            },
            cancel: () => {},
        });
    }

    pick(recipe) {
        this.state.recipe = recipe;
        this.state.servings = "1";
        this.state.step = "servings";
    }

    // ---- servings eaten (halves allowed) ----
    get servingsEaten() {
        return num(this.state.servings);
    }

    onServingsInput(ev) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state.servings = cleaned;
    }

    stepServings(delta) {
        this.state.servings = String(Math.max(0.5, this.servingsEaten + delta * 0.5));
    }

    get preview() {
        const per = this.state.recipe.per_serving;
        const n = this.servingsEaten;
        return {
            calories: fmt(per.calories * n),
            protein: fmt(per.protein * n),
            carbs: fmt(per.carbs * n),
            fat: fmt(per.fat * n),
        };
    }

    async confirm() {
        if (this.servingsEaten <= 0) {
            return;
        }
        this.state.busy = true;
        try {
            if (this.props.entry) {
                await this.orm.call("gym.meal_log", "set_servings", [
                    [this.props.entry.id],
                    this.servingsEaten,
                ]);
            } else {
                await this.orm.call("gym.meal_log", "log_recipe", [
                    this.state.recipe.id,
                    this.props.meal,
                    this.props.date,
                    this.servingsEaten,
                ]);
            }
            this.props.onDone();
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
}
