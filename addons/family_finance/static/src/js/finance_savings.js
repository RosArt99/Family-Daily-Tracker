/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { FinanceEntryDialog } from "./finance_dialogs";

// The Savings tab: how much you have put aside, whose income it came from, which plan it is for
// and the latest transfers. "Transfer" moves money out of this month's income into savings.
class FinanceSavings extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("finance.overview", "get_savings", []);
    }

    // `currency` defaults to the base (company) currency; pass a row's own currency to show an
    // amount in the currency it was saved in.
    money(value, currency) {
        const { symbol, position, decimals } = currency || this.state.data.currency;
        const text = Math.abs(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        const sign = value < 0 ? "−" : "";
        return position === "before" ? `${sign}${symbol}${text}` : `${sign}${text} ${symbol}`;
    }

    initial(name) {
        return (name || "?").trim().charAt(0).toUpperCase();
    }

    openDialog(props) {
        this.dialogService.add(FinanceEntryDialog, {
            kind: "saving",
            onSaved: () => this.load(),
            ...props,
        });
    }

    transfer() {
        this.openDialog({ defaults: { savingKind: "deposit" } });
    }

    withdraw() {
        this.openDialog({ defaults: { savingKind: "withdraw" } });
    }

    edit(row) {
        this.openDialog({ resId: row.id });
    }

    openPlan(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "finance.plan",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAll() {
        this.actionService.doAction("family_finance.action_finance_saving_list");
    }
}

FinanceSavings.template = "family_finance.FinanceSavings";
FinanceSavings.props = ["*"];

registry.category("actions").add("family_finance.savings", FinanceSavings);
