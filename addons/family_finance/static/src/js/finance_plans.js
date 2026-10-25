/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { shrinkImage } from "./finance_dialogs";

const COVER_SIDE = 1000;

// The three stages of a plan, in the order it moves through them.
const STAGES = [
    { key: "planning", label: _t("Planning"), icon: "fa-lightbulb-o" },
    { key: "saving", label: _t("Saving"), icon: "fa-university" },
    { key: "done", label: _t("Done"), icon: "fa-check" },
];

// Accepts "12", "12.5" or "12,5" (phone keyboards); anything else counts as 0.
function num(value) {
    const n = parseFloat(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}

function decimalOnly(ev) {
    const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
    ev.target.value = cleaned;
    return cleaned;
}

function formatMoney(value, currency) {
    const { symbol, position, decimals } = currency;
    const text = Math.abs(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
    const sign = value < 0 ? "−" : "";
    return position === "before" ? `${sign}${symbol}${text}` : `${sign}${text} ${symbol}`;
}

export function planImageUrl(plan, size = "512x512") {
    return `/web/image/finance.plan/${plan.id}/image/${size}?unique=${encodeURIComponent(plan.image)}`;
}

// "in 8 months" / "in 12 days" / "3 days ago" for a plan's date.
export function whenLabel(plan) {
    if (!plan.target_date) {
        return "";
    }
    const days = plan.days_left;
    if (days === 0) {
        return _t("today");
    }
    if (days < 0) {
        return _t("%s days ago", -days);
    }
    if (days < 60) {
        return _t("in %s days", days);
    }
    return _t("in %s months", Math.round(days / 30.4));
}

// ---------------------------------------------------------------------------------------------
// The Plans tab: every trip / big purchase as a card, in three stages - Planning (an idea with a
// price tag), Saving (money is being put aside) and Done (bought, or been there).
// ---------------------------------------------------------------------------------------------
class FinancePlans extends Component {
    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.stages = STAGES;
        this.state = useState({ data: null, tab: "saving" });
        onWillStart(async () => {
            await this.load();
            // Open on the stage you are most likely after: money being saved, else the ideas.
            const first = ["saving", "planning", "done"].find((key) => this.plansIn(key).length);
            this.state.tab = first || "planning";
        });
    }

    async load() {
        this.state.data = await this.orm.call("finance.plan", "get_plans", []);
    }

    money(value) {
        return formatMoney(value, this.state.data.currency);
    }

    plansIn(stage) {
        return this.state.data.plans.filter((plan) => plan.state === stage);
    }

    get visiblePlans() {
        return this.plansIn(this.state.tab);
    }

    setTab(key) {
        this.state.tab = key;
    }

    coverStyle(plan) {
        return plan.image ? `background-image: url('${planImageUrl(plan)}')` : "";
    }

    when(plan) {
        return whenLabel(plan);
    }

    shortDate(plan) {
        const [y, m, d] = plan.target_date.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    }

    // ---- actions ----
    newPlan() {
        this.dialog.add(PlanDialog, { onSaved: () => this.reloadTo("planning") });
    }

    openPlan(plan) {
        this.dialog.add(PlanDialog, { planId: plan.id, onSaved: () => this.load() });
    }

    async reloadTo(tab) {
        await this.load();
        this.state.tab = tab;
    }

    async setStage(plan, state) {
        await this.orm.call("finance.plan", "set_plan_state", [plan.id, state]);
        await this.reloadTo(state);
    }

    markDone(plan) {
        this.dialog.add(PlanDoneDialog, {
            plan,
            money: (value) => this.money(value),
            onDone: async (payout) => {
                await this.orm.call("finance.plan", "set_plan_state", [plan.id, "done", payout]);
                await this.reloadTo("done");
            },
        });
    }

    moveSavings(plan) {
        this.dialog.add(PlanMoveDialog, { plan, onDone: () => this.load() });
    }
}

FinancePlans.template = "family_finance.FinancePlans";
FinancePlans.props = ["*"];
registry.category("actions").add("family_finance.plans", FinancePlans);

// Mark a plan Done: when it has money saved, ask whether that money was spent on it.
export class PlanDoneDialog extends Component {
    static template = "family_finance.PlanDoneDialog";
    static components = { Dialog };
    static props = {
        plan: Object,
        money: Function,
        onDone: Function,
        close: Function,
    };

    finish(payout) {
        this.props.onDone(payout);
        this.props.close();
    }
}

// ---------------------------------------------------------------------------------------------
// New / edit plan: one window with the photo, type, dates, the budget broken into items, what has
// been saved for it so far and notes.
// ---------------------------------------------------------------------------------------------
export class PlanDialog extends Component {
    static template = "family_finance.PlanDialog";
    static components = { Dialog };
    static props = {
        planId: { type: Number, optional: true },
        onSaved: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.fileRef = useRef("file");
        this.nextKey = 1;
        this.state = useState({
            plan: null,
            name: "",
            kind: "travel",
            targetDate: "",
            dateTo: "",
            notes: "",
            lines: [],
            // undefined: the photo is untouched; false: removed; "data..." a new one
            image: undefined,
            preview: "",
            error: "",
            saving: false,
            currency: null,
        });
        onWillStart(async () => {
            const [currency, plan] = await Promise.all([
                this.orm.call("finance.overview", "get_currency_info", []),
                this.props.planId ? this.orm.call("finance.plan", "get_plan", [this.props.planId]) : null,
            ]);
            this.state.currency = currency;
            if (plan) {
                this.state.plan = plan;
                this.state.name = plan.name;
                this.state.kind = plan.kind;
                this.state.targetDate = plan.target_date || "";
                this.state.dateTo = plan.date_to || "";
                this.state.notes = plan.notes;
                this.state.lines = plan.lines.map((line) => this.makeLine(line.name, line.amount));
                this.state.preview = plan.image ? planImageUrl(plan) : "";
            } else {
                this.state.lines = [this.makeLine("", "")];
            }
        });
    }

    get title() {
        return this.props.planId ? _t("Plan") : _t("New plan");
    }

    makeLine(name, amount) {
        return { key: this.nextKey++, name, amount: amount ? String(amount) : "" };
    }

    money(value) {
        return formatMoney(value, this.state.currency);
    }

    get isTravel() {
        return this.state.kind === "travel";
    }

    // ---- budget items ----
    get budget() {
        return this.state.lines.reduce((sum, line) => sum + num(line.amount), 0);
    }

    addLine() {
        this.state.lines.push(this.makeLine("", ""));
    }

    removeLine(line) {
        this.state.lines = this.state.lines.filter((other) => other !== line);
    }

    onAmountInput(ev, line) {
        line.amount = decimalOnly(ev);
    }

    // ---- photo ----
    pickPhoto() {
        this.fileRef.el.click();
    }

    async onPhotoChosen(ev) {
        const file = ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        try {
            const url = await shrinkImage(file, COVER_SIDE);
            this.state.image = url.split(",")[1];
            this.state.preview = url;
        } catch {
            this.state.error = _t("That file could not be read as a photo.");
        }
    }

    removePhoto() {
        this.state.image = false;
        this.state.preview = "";
    }

    // ---- saved so far ----
    moveSavings() {
        this.dialog.add(PlanMoveDialog, {
            plan: this.state.plan,
            onDone: async (plan) => {
                this.state.plan = plan;
                if (this.props.onSaved) {
                    this.props.onSaved(plan);
                }
            },
        });
    }

    historyLabel(row) {
        if (row.move === "payout") {
            return _t("Paid out");
        }
        if (row.move === "transfer") {
            return row.kind === "deposit" ? _t("Moved in") : _t("Moved out");
        }
        return row.kind === "deposit" ? _t("Saved") : _t("Withdrawn");
    }

    historyMoney(row) {
        return formatMoney(row.amount, row.currency);
    }

    // ---- save / delete ----
    async save() {
        const { state } = this;
        state.error = "";
        if (!state.name.trim()) {
            state.error = _t("Give the plan a name.");
            return;
        }
        if (state.lines.some((line) => (line.name.trim() || num(line.amount)) && num(line.amount) <= 0)) {
            state.error = _t("Every budget item needs an amount.");
            return;
        }
        state.saving = true;
        try {
            const data = {
                id: this.props.planId || false,
                name: state.name,
                kind: state.kind,
                target_date: state.targetDate || false,
                date_to: this.isTravel ? state.dateTo || false : false,
                notes: state.notes,
                lines: state.lines.map((line) => ({ name: line.name, amount: num(line.amount) })),
            };
            if (state.image !== undefined) {
                data.image = state.image;
            }
            const plan = await this.orm.call("finance.plan", "save_plan", [data]);
            if (this.props.onSaved) {
                this.props.onSaved(plan);
            }
            this.props.close();
        } catch (error) {
            state.error = (error.data && error.data.message) || error.message || String(error);
        } finally {
            state.saving = false;
        }
    }

    askDelete() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete plan"),
            body: _t(
                "Delete %s? The money saved for it stays in your savings, as general savings.",
                this.state.plan.name
            ),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.unlink("finance.plan", [this.props.planId]);
                if (this.props.onSaved) {
                    this.props.onSaved();
                }
                this.props.close();
            },
            cancel: () => {},
        });
    }
}

// ---------------------------------------------------------------------------------------------
// Move money you have already put aside from the general savings to a plan (or back). It is not
// new saving - it only says what the money is for - so it does not touch the month's numbers.
// ---------------------------------------------------------------------------------------------
export class PlanMoveDialog extends Component {
    static template = "family_finance.PlanMoveDialog";
    static components = { Dialog };
    static props = {
        // The plan to move to; without it the window first asks which one.
        plan: { type: Object, optional: true },
        onDone: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            plans: [],
            planId: this.props.plan ? this.props.plan.id : false,
            planName: this.props.plan ? this.props.plan.name : "",
            direction: "in",
            options: [],
            pick: 0,
            amount: "",
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            if (!this.props.plan) {
                const data = await this.orm.call("finance.plan", "get_plans", []);
                this.state.plans = data.plans.filter((plan) => plan.state !== "done");
                if (this.state.plans.length) {
                    this.choosePlan(this.state.plans[0]);
                }
            }
            if (this.state.planId) {
                await this.loadOptions();
            }
        });
    }

    async loadOptions() {
        this.state.options = await this.orm.call("finance.plan", "get_move_options", [this.state.planId]);
        this.state.pick = 0;
        this.state.amount = "";
    }

    async choosePlan(plan) {
        this.state.planId = plan.id;
        this.state.planName = plan.name;
        await this.loadOptions();
    }

    setDirection(direction) {
        this.state.direction = direction;
        this.state.pick = 0;
        this.state.amount = "";
    }

    // What can be moved from the chosen source: general savings going in, the plan's own coming out.
    available(option) {
        return this.state.direction === "in" ? option.general : option.plan;
    }

    // The people/currencies that hold something to move in the chosen direction.
    get sources() {
        return this.state.options
            .map((option, index) => ({ ...option, index }))
            .filter((option) => this.available(option) > 0);
    }

    get chosen() {
        const sources = this.sources;
        return sources.find((option) => option.index === this.state.pick) || sources[0];
    }

    money(value, currency) {
        return formatMoney(value, currency);
    }

    onAmountInput(ev) {
        this.state.amount = decimalOnly(ev);
    }

    moveAll() {
        const option = this.chosen;
        if (option) {
            this.state.amount = String(Math.floor(this.available(option) * 100) / 100);
        }
    }

    async save() {
        const { state } = this;
        const option = this.chosen;
        state.error = "";
        if (!option || num(state.amount) <= 0) {
            state.error = _t("Enter how much to move.");
            return;
        }
        state.saving = true;
        try {
            const plan = await this.orm.call("finance.plan", "move_savings", [
                state.planId,
                option.user_id,
                option.currency.id,
                num(state.amount),
                state.direction,
            ]);
            this.props.onDone(plan);
            this.props.close();
        } catch (error) {
            state.error = (error.data && error.data.message) || error.message || String(error);
        } finally {
            state.saving = false;
        }
    }
}
