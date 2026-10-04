/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { FinanceEntryDialog, FinanceLimitsDialog } from "./finance_dialogs";

// The Finance landing screen: one month at a glance - what came in, what went on groceries
// (food vs household), what is left, a 6-month trend and the plans being saved for. All the
// numbers come from one server call (finance.overview.get_overview).
class FinanceOverview extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
    }

    async load(year, month) {
        this.state.data = await this.orm.call("finance.overview", "get_overview", [], { year, month });
    }

    shiftMonth(delta) {
        const { year, month } = this.state.data;
        const d = new Date(year, month - 1 + delta, 1);
        return this.load(d.getFullYear(), d.getMonth() + 1);
    }

    money(value) {
        const { symbol, position, decimals } = this.state.data.currency;
        const text = Math.abs(value || 0).toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        const sign = value < 0 ? "−" : "";
        return position === "before" ? `${sign}${symbol}${text}` : `${sign}${text} ${symbol}`;
    }

    // Share of `part` in `whole`, as a CSS percentage (0 when there is nothing to divide).
    pct(part, whole) {
        return whole > 0 ? Math.round((part / whole) * 100) : 0;
    }

    get trendMax() {
        return Math.max(1, ...this.state.data.trend.flatMap((m) => [m.income, m.spent]));
    }

    trendHeight(value) {
        return Math.max(value > 0 ? 3 : 0, Math.round((value / this.trendMax) * 100));
    }

    initial(name) {
        return (name || "?").trim().charAt(0).toUpperCase();
    }

    // "+ Add ..." opens the friendly entry dialog; the screen refreshes when it saves.
    openNew(kind) {
        this.dialogService.add(FinanceEntryDialog, {
            kind,
            onSaved: () => this.load(this.state.data.year, this.state.data.month),
        });
    }

    openLimits() {
        this.dialogService.add(FinanceLimitsDialog, {
            onSaved: () => this.load(this.state.data.year, this.state.data.month),
        });
    }

    // Green under 80% of a limit, amber from 80%, red once it is passed.
    limitClass(limit) {
        if (limit.percent >= 100) {
            return "o_over";
        }
        return limit.percent >= 80 ? "o_warn" : "";
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

    openAction(xmlid) {
        this.actionService.doAction(xmlid);
    }
}

FinanceOverview.template = "family_finance.FinanceOverview";
FinanceOverview.props = ["*"];

registry.category("actions").add("family_finance.overview", FinanceOverview);
