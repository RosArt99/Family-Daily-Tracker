/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { CATEGORIES, FinanceCategoryPicker, FinanceEntryDialog } from "./finance_dialogs";

// The Expenses tab: this month's spending at the top, then one big button per category (the same
// idea as the Shopping List & Stock landing) that opens that category's list.
class FinanceExpenses extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.state = useState({ data: null });
        this.categories = CATEGORIES;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("finance.overview", "get_overview", []);
    }

    money(value) {
        const { symbol, position, decimals } = this.state.data.currency;
        const text = Math.abs(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        return position === "before" ? `${symbol}${text}` : `${text} ${symbol}`;
    }

    amountFor(category) {
        const row = this.state.data.expenses.rows.find((r) => r.key === category.key);
        return row ? row.amount : 0;
    }

    open(category) {
        this.actionService.doAction(category.action);
    }

    add() {
        this.dialogService.add(FinanceCategoryPicker, {
            onPick: (kind) =>
                this.dialogService.add(FinanceEntryDialog, { kind, onSaved: () => this.load() }),
        });
    }
}

FinanceExpenses.template = "family_finance.FinanceExpenses";
FinanceExpenses.props = ["*"];

registry.category("actions").add("family_finance.expenses", FinanceExpenses);
