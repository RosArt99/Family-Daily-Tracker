/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { Component, onWillStart, useState } from "@odoo/owl";
import { AddFoodDialog } from "./meals_recipes";

const MEAL_STYLE = {
    breakfast: { icon: "fa-coffee", color: "#f0a30a" },
    lunch: { icon: "fa-cutlery", color: "#1e88e5" },
    dinner: { icon: "fa-moon-o", color: "#ef7b5d" },
    snack: { icon: "fa-lemon-o", color: "#8e5bb5" },
};

function pad(n) {
    return String(n).padStart(2, "0");
}

// Food diary in the FatSecret mould: pick a day, see calories remaining/consumed against the
// daily goal, and log food per meal (Breakfast / Lunch / Dinner / Snacks) with a "+".
class MealsDiary extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.state = useState({ date: null, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        const data = await this.orm.call("gym.meal_log", "get_diary", [this.state.date]);
        this.state.date = data.date;
        this.state.data = data;
    }

    // ---- day navigation ----
    get dateLabel() {
        const data = this.state.data;
        if (data && data.is_today) {
            return _t("Today");
        }
        const [y, m, d] = this.state.date.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
        });
    }

    async shift(days) {
        const [y, m, d] = this.state.date.split("-").map(Number);
        const next = new Date(y, m - 1, d + days);
        this.state.date = `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}`;
        await this.load();
    }

    async goToday() {
        this.state.date = null;
        await this.load();
    }

    // ---- presentation helpers ----
    mealStyle(key) {
        return MEAL_STYLE[key] || MEAL_STYLE.snack;
    }

    percent(value, goal) {
        return goal > 0 ? Math.min(100, Math.round((value / goal) * 100)) : 0;
    }

    get macros() {
        const { totals, goals } = this.state.data;
        return [
            { key: "protein", label: _t("Protein"), value: totals.protein, goal: goals.protein },
            { key: "carbs", label: _t("Carbs"), value: totals.carbs, goal: goals.carbs },
            { key: "fat", label: _t("Fat"), value: totals.fat, goal: goals.fat },
        ];
    }

    // ---- actions (all forms open as dialogs and refresh the diary when closed) ----
    openForm(title, { resId, context } = {}) {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: title,
                res_model: "gym.meal_log",
                res_id: resId || false,
                views: [[false, "form"]],
                target: "new",
                context: context || {},
            },
            { onClose: () => this.load() }
        );
    }

    // "+" : first choose the source - Groceries (pantry) or My Saved Food (recipes).
    addFood(meal, mealLabel) {
        this.dialog.add(AddFoodDialog, {
            meal,
            mealLabel,
            date: this.state.date,
            onPantry: () => this.addFromPantry(meal),
            onDone: () => this.load(),
        });
    }

    // Search the pantry (Groceries catalog, in-stock food first), then confirm the amount.
    addFromPantry(meal) {
        this.dialog.add(SelectCreateDialog, {
            title: _t("Add food"),
            resModel: "groceries.product",
            multiSelect: false,
            noCreate: true,
            context: { search_default_filter_in_stock: 1 },
            onSelected: ([productId]) =>
                this.openForm(_t("Add food"), {
                    context: {
                        default_meal_type: meal,
                        default_date: this.state.date,
                        default_product_id: productId,
                    },
                }),
        });
    }

    quickAdd(meal) {
        this.openForm(_t("Quick add"), {
            context: { default_meal_type: meal, default_date: this.state.date },
        });
    }

    editEntry(entry) {
        if (entry.recipe_id) {
            // A recipe entry is only about how many servings you ate.
            this.dialog.add(AddFoodDialog, { entry, onDone: () => this.load() });
            return;
        }
        this.openForm(entry.name || _t("Food"), { resId: entry.id });
    }

    deleteEntry(entry) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete entry"),
            body: _t("Remove %s from the diary?", entry.name),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.unlink("gym.meal_log", [entry.id]);
                await this.load();
            },
            cancel: () => {},
        });
    }

    editGoals() {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Daily goals"),
                res_model: "gym.profile",
                res_id: this.state.data.profile_id,
                views: [[false, "form"]],
                target: "new",
            },
            { onClose: () => this.load() }
        );
    }
}

MealsDiary.template = "family_gym.MealsDiary";
MealsDiary.props = ["*"];

registry.category("actions").add("family_gym.meals_diary", MealsDiary);
