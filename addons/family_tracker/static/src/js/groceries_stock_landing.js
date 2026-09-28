/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const CATEGORIES = [
    {
        state: "to_buy",
        label: _t("To Buy"),
        hint: _t("What still needs buying"),
        icon: "fa-shopping-cart",
        action: "family_tracker.action_groceries_stock_to_buy",
        className: "o_gsl_to_buy",
    },
    {
        state: "in_stock",
        label: _t("In Stock"),
        hint: _t("What you actually have"),
        icon: "fa-check-circle",
        action: "family_tracker.action_groceries_stock_in_stock",
        className: "o_gsl_in_stock",
    },
    {
        state: "consumed",
        label: _t("Consumed / Discarded"),
        hint: _t("What you used up or threw out"),
        icon: "fa-archive",
        action: "family_tracker.action_groceries_stock_consumed",
        className: "o_gsl_consumed",
    },
];

// Landing page for "Shopping List & Stock": three big buttons, one per lifecycle stage,
// instead of dropping straight into one Kanban with all three mixed together. Each opens the
// very same Kanban/List/form trio (groceries_stock_entry_views.xml), just pre-filtered to its
// own state - Kanban there still shows one card per physical pack, List still rolls them up
// by product, exactly like the combined view used to.
class GroceriesStockLanding extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.categories = CATEGORIES;
        this.state = useState({ counts: {} });
        onWillStart(() => this.loadCounts());
    }

    async loadCounts() {
        const rows = await this.orm.readGroup("groceries.stock_entry", [], ["quantity:sum"], ["state"]);
        const counts = {};
        for (const row of rows) {
            counts[row.state] = row.state_count || 0;
        }
        this.state.counts = counts;
    }

    countFor(category) {
        return this.state.counts[category.state] || 0;
    }

    open(category) {
        this.actionService.doAction(category.action);
    }
}

GroceriesStockLanding.template = "family_tracker.GroceriesStockLanding";
GroceriesStockLanding.props = ["*"];

registry.category("actions").add("family_tracker.stock_landing", GroceriesStockLanding);
