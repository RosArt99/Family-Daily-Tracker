/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";

// The "Sort" button of Shopping List & Stock (Kanban and List): by product name, or by the date
// the pack got its current status. The single source of truth for the chosen order is the
// model's own `orderBy` - the button only changes it, and the List renderer
// (groceries_stock_list.js) reads it back.

// "Date added" depends on the status the page shows: when it was put on the shopping list,
// bought, or consumed.
const DATE_FIELD_BY_STATE = {
    to_buy: "create_date",
    in_stock: "purchase_date",
    consumed: "consumed_date",
};

// `template` is the controller's own template, extended (see groceries_stock_sort.xml) to put the
// button in the control panel's always-visible right-hand area. Odoo hides everything from
// `buttonTemplate` behind the little arrow next to "New" on a phone, which is why the button
// is not delivered that way.
export function withSort(Controller, template) {
    return class extends Controller {
        static template = template;
        static components = { ...Controller.components, Dropdown, DropdownItem };

        // Each landing button opens the list with context {'default_state': ...}.
        get dateField() {
            const state = (this.props.context || {}).default_state;
            return DATE_FIELD_BY_STATE[state] || "create_date";
        }

        // Derived from the model, not stored here: after a search or a "Mark Consumed" reload
        // Odoo keeps the previous orderBy, so the highlighted item always matches the screen.
        get sortMode() {
            const orderBy = this.model.root.orderBy;
            return orderBy.length && orderBy[0].name === "product_id" ? "name" : "date";
        }

        async sortBy(mode) {
            const orderBy =
                mode === "name"
                    ? [{ name: "product_id", asc: true }]
                    : [{ name: this.dateField, asc: false }, { name: "id", asc: false }];
            await this.model.load({ orderBy });
            this.render(true);
        }
    };
}

registry.category("views").add("groceries_stock_kanban", {
    ...kanbanView,
    Controller: withSort(KanbanController, "family_tracker.StockKanbanView"),
});
