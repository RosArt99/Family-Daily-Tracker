/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { GroceriesPickerDialog } from "./groceries_picker";

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
            cookedWeight: "",
            categoryId: false,
            categories: [],
            newCategory: "",
            ingredients: [],
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            this.state.categories = (await this.orm.call("gym.recipe.category", "get_categories", [])).categories;
            if (this.props.recipeId) {
                const recipe = await this.orm.call("gym.recipe", "get_recipe", [this.props.recipeId]);
                this.state.categoryId = recipe.category_id || false;
                this.state.name = recipe.name;
                this.state.description = recipe.description;
                this.state.servings = String(recipe.servings);
                this.state.cookedWeight = recipe.cooked_weight_g ? String(recipe.cooked_weight_g) : "";
                this.state.ingredients = recipe.ingredients.map((line) =>
                    this.makeIngredient(line.product_id, line.name, line.quantity_g, line.per100, line.sub_recipe_id)
                );
            }
        });
    }

    get title() {
        return this.props.recipeId ? _t("Edit recipe") : _t("New recipe");
    }

    // An ingredient is a Groceries product, or - `subRecipeId` - another recipe (crepes + filling).
    makeIngredient(productId, name, quantity, per100, subRecipeId = false) {
        return {
            key: this.nextKey++,
            product_id: productId,
            sub_recipe_id: subRecipeId,
            name,
            quantity: String(quantity),
            per100,
            // Products without nutrition data would silently count as 0 kcal.
            missing: !Object.values(per100).some((value) => value > 0),
        };
    }

    // ---- category: one of the shelves, or a new one typed in ----
    async addCategory() {
        const name = this.state.newCategory.trim();
        if (!name) {
            return;
        }
        const category = await this.orm.call("gym.recipe.category", "create_category", [name]);
        if (!this.state.categories.some((other) => other.id === category.id)) {
            this.state.categories.push(category);
        }
        this.state.categoryId = category.id;
        this.state.newCategory = "";
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
        this.dialog.add(GroceriesPickerDialog, {
            title: _t("Add ingredients"),
            multiSelect: true,
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

    // Another saved recipe as an ingredient, by the weight of it that goes in. Its own
    // ingredients stay its business: change the filling and every dish using it follows.
    addRecipe() {
        this.dialog.add(RecipePickerDialog, {
            excludeId: this.props.recipeId,
            onSelected: (recipe) => {
                if (this.state.ingredients.some((line) => line.sub_recipe_id === recipe.id)) {
                    return;
                }
                this.state.ingredients.push(
                    this.makeIngredient(false, recipe.name, Math.round(recipe.serving_weight_g) || 100, recipe.per_100g, recipe.id)
                );
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

    onCookedInput(ev) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state.cookedWeight = cleaned;
    }

    // What the finished dish weighs: the weight typed after cooking, else the ingredients' own.
    get dishWeight() {
        return num(this.state.cookedWeight) || this.totals.weight;
    }

    get servingWeight() {
        return this.dishWeight / this.servingsCount;
    }

    get kcalPer100() {
        return this.dishWeight ? (this.totals.calories / this.dishWeight) * 100 : 0;
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
                    category_id: state.categoryId,
                    description: state.description,
                    servings: this.servingsCount,
                    cooked_weight_g: num(state.cookedWeight),
                    ingredients: state.ingredients.map((line) => ({
                        product_id: line.product_id,
                        sub_recipe_id: line.sub_recipe_id,
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

// Pick one saved recipe - to use it as an ingredient of another recipe (crepes + their filling).
export class RecipePickerDialog extends Component {
    static template = "family_gym.RecipePickerDialog";
    static components = { Dialog };
    static props = {
        // The recipe being edited cannot be an ingredient of itself.
        excludeId: { type: Number, optional: true },
        onSelected: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ search: "", recipes: [] });
        this.searchDebounced = useDebounced(() => this.load(), 250);
        onWillStart(() => this.load());
    }

    async load() {
        const recipes = await this.orm.call("gym.recipe", "get_saved", [this.state.search]);
        this.state.recipes = recipes.filter((recipe) => recipe.id !== this.props.excludeId);
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.searchDebounced();
    }

    fmt(value) {
        return fmt(value);
    }

    pick(recipe) {
        this.props.onSelected(recipe);
        this.props.close();
    }
}

// File one saved dish under a category: tap a shelf and it is done (quick when going through many
// dishes). A new shelf can be typed in on the spot.
export class RecipeCategoryDialog extends Component {
    static template = "family_gym.RecipeCategoryDialog";
    static components = { Dialog };
    static props = {
        recipe: Object,
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ categories: [], newName: "", error: "" });
        onWillStart(async () => {
            this.state.categories = (await this.orm.call("gym.recipe.category", "get_categories", [])).categories;
        });
    }

    async choose(categoryId) {
        await this.orm.call("gym.recipe", "set_category", [this.props.recipe.id, categoryId]);
        this.props.onDone();
        this.props.close();
    }

    async addAndChoose() {
        const name = this.state.newName.trim();
        if (!name) {
            return;
        }
        try {
            const category = await this.orm.call("gym.recipe.category", "create_category", [name]);
            await this.choose(category.id);
        } catch (error) {
            this.state.error = (error.data && error.data.message) || error.message || String(error);
        }
    }
}

// Add, rename and delete categories. Deleting one keeps its dishes: they become "not filed yet".
export class CategoriesDialog extends Component {
    static template = "family_gym.CategoriesDialog";
    static components = { Dialog };
    static props = {
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({ categories: [], newName: "", error: "" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.categories = (await this.orm.call("gym.recipe.category", "get_categories", [])).categories;
    }

    async guard(action) {
        this.state.error = "";
        try {
            await action();
            await this.load();
            this.props.onDone();
        } catch (error) {
            this.state.error = (error.data && error.data.message) || error.message || String(error);
            await this.load();
        }
    }

    add() {
        const name = this.state.newName.trim();
        if (!name) {
            return;
        }
        return this.guard(async () => {
            await this.orm.call("gym.recipe.category", "create_category", [name]);
            this.state.newName = "";
        });
    }

    rename(category, ev) {
        const name = ev.target.value.trim();
        if (!name || name === category.name) {
            ev.target.value = category.name;
            return;
        }
        return this.guard(() => this.orm.call("gym.recipe.category", "rename", [[category.id], name]));
    }

    remove(category) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete category"),
            body: category.count
                ? _t("Delete %s? Its %s dishes stay, they just have no category.", category.name, category.count)
                : _t("Delete %s?", category.name),
            confirmLabel: _t("Delete"),
            confirm: () => this.guard(() => this.orm.unlink("gym.recipe.category", [category.id])),
            cancel: () => {},
        });
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
        // The diary the food goes into (null: the current user's) - one of you can fill the other's.
        userId: { type: [Number, Boolean], optional: true },
        // Repeating a recipe from the history: open it straight at the amount, starting from
        // the grams of last time.
        recipeId: { type: Number, optional: true },
        grams: { type: Number, optional: true },
        onPantry: { type: Function, optional: true },
        onRestaurants: { type: Function, optional: true },
        onHistory: { type: Function, optional: true },
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({
            step: this.props.entry || this.props.recipeId ? "servings" : "menu",
            search: "",
            recipes: [],
            // Saved food is browsed by category: "all", "none" (not filed yet) or a category id.
            category: "all",
            categories: [],
            uncategorized: 0,
            total: 0,
            history: [],
            recipe: null,
            // How the amount is typed in: grams off the kitchen scale (default) or servings.
            mode: "g",
            // Which of the two fields the person actually typed: the other one is derived from it,
            // so flipping the tabs back and forth never drifts through rounding.
            driver: "g",
            grams: "",
            servings: this.props.entry ? String(this.props.entry.servings) : "1",
            busy: false,
        });
        this.searchDebounced = useDebounced(() => this.loadRecipes(), 250);
        onWillStart(async () => {
            const known = this.props.entry || this.props.recipeId;
            if (known) {
                this.state.recipe = await this.orm.call("gym.recipe", "get_recipe", [
                    this.props.entry ? this.props.entry.recipe_id : this.props.recipeId,
                ]);
                this.state.grams = String(Math.round(this.props.entry ? this.props.entry.quantity_g : this.props.grams));
            } else {
                this.state.history = await this.orm.call("gym.meal_log", "get_history", [this.props.userId || false]);
            }
        });
    }

    // Back is for dialogs that opened at the menu; one opened on a recipe is simply closed.
    get canGoBack() {
        return this.state.step !== "menu" && !this.props.entry && !this.props.recipeId;
    }

    // ---- history ----
    repeat(item) {
        this.props.close();
        this.props.onHistory(item);
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

    restaurants() {
        this.props.close();
        this.props.onRestaurants();
    }

    async openSaved() {
        this.state.step = "saved";
        await this.loadRecipes();
    }

    // ---- saved recipes ----
    async loadRecipes() {
        const [recipes, categories] = await Promise.all([
            this.orm.call("gym.recipe", "get_saved", [this.state.search]),
            this.orm.call("gym.recipe.category", "get_categories", []),
        ]);
        this.state.recipes = recipes;
        this.state.categories = categories.categories;
        this.state.uncategorized = categories.uncategorized;
        this.state.total = categories.total;
        // A category that was deleted meanwhile no longer filters anything.
        if (typeof this.state.category === "number" && !categories.categories.some((c) => c.id === this.state.category)) {
            this.state.category = "all";
        }
    }

    setCategory(key) {
        this.state.category = key;
    }

    // The dishes of the chosen category, grouped under their category's name when browsing all.
    get recipeGroups() {
        const { recipes, category, categories } = this.state;
        if (category === "none") {
            return [{ key: "none", title: "", recipes: recipes.filter((r) => !r.category_id) }];
        }
        if (category !== "all") {
            return [{ key: category, title: "", recipes: recipes.filter((r) => r.category_id === category) }];
        }
        const groups = categories.map((c) => ({
            key: c.id,
            title: c.name,
            recipes: recipes.filter((r) => r.category_id === c.id),
        }));
        groups.push({ key: "none", title: _t("Not filed yet"), recipes: recipes.filter((r) => !r.category_id) });
        return groups.filter((group) => group.recipes.length);
    }

    get hasRecipes() {
        return this.recipeGroups.length > 0;
    }

    // Pick a shelf for one dish (the tag button on its card).
    fileRecipe(recipe) {
        this.dialog.add(RecipeCategoryDialog, { recipe, onDone: () => this.loadRecipes() });
    }

    manageCategories() {
        this.dialog.add(CategoriesDialog, { onDone: () => this.loadRecipes() });
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.searchDebounced();
    }

    newRecipe() {
        this.dialog.add(RecipeFormDialog, { onSaved: () => this.loadRecipes() });
    }

    // Edit the recipe that is open (not only from the list); its numbers refresh when saved.
    editOpenRecipe() {
        this.dialog.add(RecipeFormDialog, {
            recipeId: this.state.recipe.id,
            onSaved: (recipe) => {
                this.state.recipe = recipe;
            },
        });
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
        // Start from one serving's weight: a small correction is then a couple of taps.
        this.state.grams = String(Math.round(recipe.serving_weight_g));
        this.state.mode = "g";
        this.state.driver = "g";
        this.state.step = "servings";
    }

    // ---- how much was eaten: grams (default) or servings (halves allowed) ----
    get servingWeight() {
        return this.state.recipe.serving_weight_g;
    }

    get gramsEaten() {
        return this.state.driver === "g" ? num(this.state.grams) : num(this.state.servings) * this.servingWeight;
    }

    get servingsEaten() {
        if (this.state.driver === "s") {
            return num(this.state.servings);
        }
        return this.servingWeight ? num(this.state.grams) / this.servingWeight : 0;
    }

    // The other way of saying the same amount ("= 1.85 servings" / "= 325 g").
    get equivalent() {
        return this.state.mode === "g"
            ? `${Math.round(this.servingsEaten * 100) / 100} ${_t("servings")}`
            : `${Math.round(this.gramsEaten)} g`;
    }

    setMode(mode) {
        if (mode === this.state.mode) {
            return;
        }
        // Show the derived value in the tab that was not typed into.
        if (mode === "g" && this.state.driver === "s") {
            this.state.grams = String(Math.round(this.gramsEaten));
        } else if (mode === "s" && this.state.driver === "g") {
            this.state.servings = String(Math.round(this.servingsEaten * 100) / 100);
        }
        this.state.mode = mode;
    }

    onGramsInput(ev) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state.grams = cleaned;
        this.state.driver = "g";
    }

    stepGrams(delta) {
        this.state.grams = String(Math.max(0, Math.round(this.gramsEaten + delta * 10)));
        this.state.driver = "g";
    }

    onServingsInput(ev) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state.servings = cleaned;
        this.state.driver = "s";
    }

    stepServings(delta) {
        this.state.servings = String(Math.max(0.5, this.servingsEaten + delta * 0.5));
        this.state.driver = "s";
    }

    // Nutrition of what was eaten: per 100 g of the finished dish x grams.
    get preview() {
        const per = this.state.recipe.per_100g;
        const f = this.gramsEaten / 100;
        return {
            calories: fmt(per.calories * f),
            protein: fmt(per.protein * f),
            carbs: fmt(per.carbs * f),
            fat: fmt(per.fat * f),
        };
    }

    async confirm() {
        if (this.gramsEaten <= 0) {
            return;
        }
        this.state.busy = true;
        // Send what was actually typed (grams or servings), not a converted number.
        const amount = this.state.driver === "g" ? { grams: this.gramsEaten } : { servings: this.servingsEaten };
        try {
            if (this.props.entry) {
                await this.orm.call("gym.meal_log", "set_recipe_amount", [[this.props.entry.id]], amount);
            } else {
                await this.orm.call(
                    "gym.meal_log",
                    "log_recipe",
                    [this.state.recipe.id, this.props.meal, this.props.date],
                    { ...amount, user_id: this.props.userId || false }
                );
            }
            this.props.onDone();
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
}

// "From Groceries": how many grams of a product did you eat. Same look as the recipe's amount
// screen (big number, +/- 10 g, kcal and macros updating live), but the nutrition is simply the
// product's per-100 g values from Groceries - no servings, it is not a dish.
export class ProductAmountDialog extends Component {
    static template = "family_gym.ProductAmountDialog";
    static components = { Dialog };
    static props = {
        productId: Number,
        meal: { type: String, optional: true },
        mealLabel: { type: String, optional: true },
        date: { type: String, optional: true },
        // Editing the grams of a product entry that is already in the diary.
        entry: { type: Object, optional: true },
        userId: { type: [Number, Boolean], optional: true },
        // Start from this many grams (last time's, when repeating from the history).
        grams: { type: Number, optional: true },
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.presets = [50, 100, 150, 200];
        this.state = useState({
            product: null,
            grams: this.props.entry
                ? String(Math.round(this.props.entry.quantity_g))
                : String(Math.round(this.props.grams || 100)),
            busy: false,
        });
        onWillStart(async () => {
            const [product] = await this.orm.read("groceries.product", [this.props.productId], [
                "name",
                "energy_kcal_100g",
                "proteins_100g",
                "carbohydrates_100g",
                "fat_100g",
            ]);
            this.state.product = product;
        });
    }

    get title() {
        return this.state.product.name;
    }

    get gramsEaten() {
        return num(this.state.grams);
    }

    get noNutrition() {
        const p = this.state.product;
        return !(p.energy_kcal_100g || p.proteins_100g || p.carbohydrates_100g || p.fat_100g);
    }

    get preview() {
        const p = this.state.product;
        const f = this.gramsEaten / 100;
        return {
            calories: fmt(p.energy_kcal_100g * f),
            protein: fmt(p.proteins_100g * f),
            carbs: fmt(p.carbohydrates_100g * f),
            fat: fmt(p.fat_100g * f),
        };
    }

    fmt(value) {
        return fmt(value);
    }

    imageUrl() {
        return `/web/image/groceries.product/${this.props.productId}/image/128x128`;
    }

    onGramsInput(ev) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state.grams = cleaned;
    }

    stepGrams(delta) {
        this.state.grams = String(Math.max(0, Math.round(this.gramsEaten + delta * 10)));
    }

    setGrams(value) {
        this.state.grams = String(value);
    }

    async confirm() {
        if (this.gramsEaten <= 0) {
            return;
        }
        this.state.busy = true;
        try {
            if (this.props.entry) {
                await this.orm.call("gym.meal_log", "set_product_grams", [[this.props.entry.id], this.gramsEaten]);
            } else {
                await this.orm.call("gym.meal_log", "log_product", [
                    this.props.productId,
                    this.props.meal,
                    this.props.date,
                    this.gramsEaten,
                    this.props.userId || false,
                ]);
            }
            this.props.onDone();
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
}

// "Restaurants": pick a place (logos), then a dish from its menu, then how many portions you ate.
// Values are for the Polish menu (they differ between countries); the same dialog edits an entry
// that is already in the diary.
export class RestaurantDialog extends Component {
    static template = "family_gym.RestaurantDialog";
    static components = { Dialog };
    static props = {
        meal: { type: String, optional: true },
        mealLabel: { type: String, optional: true },
        date: { type: String, optional: true },
        entry: { type: Object, optional: true },
        userId: { type: [Number, Boolean], optional: true },
        // Repeating a dish from the history: open it straight at the portions of last time.
        itemId: { type: Number, optional: true },
        servings: { type: Number, optional: true },
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            step: this.props.entry || this.props.itemId ? "amount" : "list",
            restaurants: [],
            menu: null,
            search: "",
            category: "",
            item: null,
            servings: this.props.entry ? String(this.props.entry.servings) : String(this.props.servings || 1),
            busy: false,
        });
        onWillStart(async () => {
            if (this.props.entry || this.props.itemId) {
                this.state.item = await this.orm.call("gym.restaurant.item", "get_item", [
                    this.props.entry ? this.props.entry.menu_item_id : this.props.itemId,
                ]);
            } else {
                this.state.restaurants = await this.orm.call("gym.restaurant", "get_restaurants", []);
            }
        });
    }

    get title() {
        if (this.state.step === "amount") {
            return this.state.item.name;
        }
        if (this.state.step === "menu") {
            return this.state.menu.name;
        }
        return _t("Restaurants");
    }

    fmt(value) {
        return fmt(value);
    }

    logoUrl(restaurantId) {
        return `/web/image/gym.restaurant/${restaurantId}/logo/256x256`;
    }

    // ---- navigation ----
    back() {
        this.state.step = this.state.step === "amount" ? "menu" : "list";
        if (this.state.step === "list") {
            this.state.search = "";
            this.state.category = "";
        }
    }

    async openRestaurant(restaurant) {
        this.state.menu = await this.orm.call("gym.restaurant", "get_menu", [restaurant.id]);
        this.state.search = "";
        this.state.category = "";
        this.state.step = "menu";
    }

    // ---- menu list ----
    get items() {
        const search = this.state.search.trim().toLowerCase();
        return this.state.menu.items.filter(
            (item) =>
                (!this.state.category || item.category === this.state.category) &&
                (!search || item.name.toLowerCase().includes(search))
        );
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    setCategory(key) {
        this.state.category = this.state.category === key ? "" : key;
    }

    pick(item) {
        this.state.item = item;
        this.state.servings = "1";
        this.state.step = "amount";
    }

    // ---- how many portions ----
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

    setServings(value) {
        this.state.servings = String(value);
    }

    get preview() {
        const item = this.state.item;
        const n = this.servingsEaten;
        return {
            calories: fmt(item.calories * n),
            protein: fmt(item.protein * n),
            carbs: fmt(item.carbs * n),
            fat: fmt(item.fat * n),
            grams: item.serving_g ? fmt(item.serving_g * n) : 0,
        };
    }

    async confirm() {
        if (this.servingsEaten <= 0) {
            return;
        }
        this.state.busy = true;
        try {
            if (this.props.entry) {
                await this.orm.call("gym.meal_log", "set_menu_servings", [[this.props.entry.id], this.servingsEaten]);
            } else {
                await this.orm.call("gym.meal_log", "log_menu_item", [
                    this.state.item.id,
                    this.props.meal,
                    this.props.date,
                    this.servingsEaten,
                    this.props.userId || false,
                ]);
            }
            this.props.onDone();
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
}
