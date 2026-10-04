/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

// One friendly "Add ..." window for every Finance record (the same look as the Gym & Fit
// weight/exercise dialogs, in blue): a big coloured header with the amount, then soft cards -
// who, what kind, date, receipt photos, notes. The same window edits an existing record.
//
// KINDS drives what is shown; everything else is shared.
export const KINDS = {
    bill: {
        model: "finance.bill",
        title: _t("Groceries bill"),
        icon: "fa-shopping-basket",
        heroLabel: _t("Bill total"),
        amountField: "total_amount",
    },
    housing: {
        model: "finance.housing",
        title: _t("Housing payment"),
        icon: "fa-home",
        heroLabel: _t("Amount"),
        amountField: "amount",
    },
    income: {
        model: "finance.income",
        title: _t("Income"),
        icon: "fa-arrow-down",
        heroLabel: _t("Amount received"),
        amountField: "amount",
    },
    saving: {
        model: "finance.saving",
        title: _t("Savings"),
        icon: "fa-university",
        heroLabel: _t("Amount"),
        amountField: "amount",
    },
    plan: {
        model: "finance.plan",
        title: _t("Plan"),
        icon: "fa-plane",
        heroLabel: _t("What are you planning?"),
        amountField: null,
    },
};

// Which dialog handles which model (finance_views.js uses this to take over "New" / card click).
export const KIND_BY_MODEL = Object.fromEntries(Object.entries(KINDS).map(([kind, k]) => [k.model, kind]));

const HOUSING_KINDS = [
    ["rent", _t("Rent")],
    ["utilities", _t("Utilities")],
    ["electricity", _t("Electricity")],
    ["internet", _t("Internet")],
    ["other", _t("Other")],
];
const INCOME_SOURCES = [
    ["salary", _t("Salary")],
    ["bonus", _t("Bonus")],
    ["other", _t("Other")],
];
const MAX_PHOTO_SIDE = 1600;

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

function shown(value) {
    return String(Math.round(value * 100) / 100);
}

function todayString() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// A phone photo is 3-6 MB; shrink it to what a receipt needs before it travels to the server.
function shrinkImage(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error);
        reader.onload = () => {
            const img = new Image();
            img.onerror = () => reject(new Error("Not an image"));
            img.onload = () => {
                const scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(img.width, img.height));
                const canvas = document.createElement("canvas");
                canvas.width = Math.round(img.width * scale);
                canvas.height = Math.round(img.height * scale);
                canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
                resolve(canvas.toDataURL("image/jpeg", 0.82));
            };
            img.src = reader.result;
        };
        reader.readAsDataURL(file);
    });
}

let currenciesPromise = null;
// { base: {id, name, symbol, position, decimals}, list: [same, ...every active currency] }
function loadCurrencies(orm) {
    if (!currenciesPromise) {
        currenciesPromise = orm.call("finance.overview", "get_currencies", []);
    }
    return currenciesPromise;
}

export class FinanceEntryDialog extends Component {
    static template = "family_finance.EntryDialog";
    static components = { Dialog };
    static props = {
        kind: String,
        resId: { type: Number, optional: true },
        defaults: { type: Object, optional: true },
        onSaved: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.cfg = KINDS[this.props.kind];
        this.fileRef = useRef("file");
        this.housingKinds = HOUSING_KINDS;
        this.incomeSources = INCOME_SOURCES;
        const defaults = this.props.defaults || {};
        this.state = useState({
            currency: { symbol: "", position: "before" },
            base: { id: 0, symbol: "", position: "before" },
            currencies: [],
            currencyId: 0,
            rate: "",
            rateNote: "",
            amount: "",
            household: "",
            storeText: "",
            stores: [],
            date: this.props.kind === "plan" ? "" : todayString(),
            period: todayString().slice(0, 7),
            userId: session.uid || session.user_id,
            users: [],
            housingKind: "rent",
            source: "salary",
            savingKind: defaults.savingKind || "deposit",
            planId: false,
            plans: [],
            planName: "",
            planKind: "travel",
            notes: "",
            photos: [],
            removedPhotoIds: [],
            zoom: "",
            error: "",
            saving: false,
        });
        onWillStart(() => this.load());
    }

    get isEdit() {
        return Boolean(this.props.resId);
    }

    get kind() {
        return this.props.kind;
    }

    get dialogTitle() {
        return (this.isEdit ? _t("Edit ") : _t("Add ")) + this.cfg.title.toLowerCase();
    }

    // ------------------------------------------------------------------ loading

    async load() {
        const { state } = this;
        const jobs = [
            loadCurrencies(this.orm).then((c) => {
                state.base = c.base;
                state.currency = c.base;
                state.currencyId = c.base.id;
                state.currencies = c.list;
            }),
        ];
        if (this.kind !== "plan") {
            jobs.push(
                this.orm
                    .searchRead("res.users", [["share", "=", false]], ["name"], { order: "name" })
                    .then((users) => (state.users = users))
            );
        }
        if (this.kind === "bill") {
            jobs.push(this.loadStores());
        }
        if (this.kind === "saving") {
            jobs.push(
                this.orm
                    .searchRead("finance.plan", [["state", "in", ["planning", "saving"]]], ["name"], { order: "name" })
                    .then((plans) => (state.plans = plans))
            );
        }
        await Promise.all(jobs);
        if (this.isEdit) {
            await this.loadRecord();
        } else if (this.kind === "plan") {
            state.planKind = (this.props.defaults || {}).planKind || "travel";
        } else if (this.hasCurrency) {
            // Salary comes in hryvnias, savings sit in dollars (USDT); everything else is zlotys.
            const wanted = this.kind === "income" ? "UAH" : "USD";
            const match = state.currencies.find((c) => c.name === wanted);
            if (match) {
                await this.setCurrency(match.id);
            }
        }
    }

    // Stores you shopped at most recently come first.
    async loadStores() {
        const [stores, recent] = await Promise.all([
            this.orm.searchRead("finance.store", [], ["name"], { order: "name" }),
            this.orm.searchRead("finance.bill", [["store_id", "!=", false]], ["store_id"], {
                order: "date desc, id desc",
                limit: 80,
            }),
        ]);
        const rank = new Map();
        recent.forEach((bill) => {
            if (!rank.has(bill.store_id[0])) {
                rank.set(bill.store_id[0], rank.size);
            }
        });
        this.state.stores = stores.sort(
            (a, b) => (rank.has(a.id) ? rank.get(a.id) : 1e6) - (rank.has(b.id) ? rank.get(b.id) : 1e6)
        );
    }

    async loadRecord() {
        const { state } = this;
        const [rec] = await this.orm.read(this.cfg.model, [this.props.resId], []);
        state.amount = this.cfg.amountField ? shown(rec[this.cfg.amountField]) : "";
        state.notes = rec.notes || "";
        if (rec.date) {
            state.date = rec.date;
        }
        if (rec.user_id) {
            state.userId = rec.user_id[0];
        }
        if (this.kind === "bill") {
            state.household = rec.household_amount ? shown(rec.household_amount) : "";
            state.storeText = rec.store_id ? rec.store_id[1] : "";
        }
        if (this.kind === "housing") {
            state.housingKind = rec.kind;
            state.period = rec.period.slice(0, 7);
        }
        if (this.hasCurrency) {
            this.applyCurrency(rec.currency_id[0]);
            state.rate = this.trimRate(rec.rate);
            state.rateNote = _t("Saved rate");
        }
        if (this.kind === "income") {
            state.source = rec.source;
        }
        if (this.kind === "saving") {
            state.savingKind = rec.kind;
            state.planId = rec.plan_id ? rec.plan_id[0] : false;
        }
        if (rec.photo_ids && rec.photo_ids.length) {
            state.photos = rec.photo_ids.map((id) => ({
                id,
                thumb: `/web/image/finance.photo/${id}/image/256x256`,
                full: `/web/image/finance.photo/${id}/image`,
            }));
        }
    }

    // ------------------------------------------------------------------ input helpers

    // ---- currency & exchange rate (income and savings only) ----
    get hasCurrency() {
        return this.kind === "income" || this.kind === "saving";
    }

    get isForeign() {
        return this.hasCurrency && this.state.currencyId !== this.state.base.id;
    }

    get baseValue() {
        return num(this.state.amount) * num(this.state.rate);
    }

    trimRate(value) {
        return String(Math.round(value * 1e6) / 1e6);
    }

    applyCurrency(id) {
        const currency = this.state.currencies.find((c) => c.id === id);
        if (currency) {
            this.state.currencyId = id;
            this.state.currency = currency;
        }
    }

    async setCurrency(id) {
        this.applyCurrency(id);
        await this.refreshRate();
    }

    // Official National Bank of Ukraine rate for the entry's date, converted to the base
    // currency on the server; the field stays editable (you may have exchanged at another rate).
    async refreshRate() {
        const { state } = this;
        if (!this.isForeign) {
            state.rate = "1";
            state.rateNote = "";
            return;
        }
        const ticket = (this.rateTicket = (this.rateTicket || 0) + 1);
        state.rateNote = _t("Getting the NBU rate...");
        const result = await this.orm.call("finance.fx.rate", "get_rate", [state.currencyId], {
            date: state.date || todayString(),
        });
        if (ticket !== this.rateTicket) {
            return; // a newer request superseded this one
        }
        if (result.rate) {
            state.rate = this.trimRate(result.rate);
            state.rateNote = _t("NBU rate for ") + result.date;
        } else {
            state.rate = "";
            state.rateNote = _t("Could not get the rate - enter it by hand.");
        }
    }

    onDateChanged() {
        if (this.hasCurrency) {
            return this.refreshRate();
        }
    }

    onRateInput(ev) {
        this.state.rate = decimalOnly(ev);
        this.state.rateNote = _t("Entered by hand");
    }

    onAmountInput(ev) {
        this.state.amount = decimalOnly(ev);
    }

    onHouseholdInput(ev) {
        this.state.household = decimalOnly(ev);
    }

    get hasPhotos() {
        return this.kind === "bill" || this.kind === "housing";
    }

    get needsWho() {
        return this.kind !== "plan";
    }

    get whoLabel() {
        return {
            bill: _t("Paid by"),
            housing: _t("Paid by"),
            income: _t("Whose income"),
            saving: _t("From whose income"),
        }[this.kind];
    }

    get householdValue() {
        return num(this.state.household);
    }

    get food() {
        return Math.max(num(this.state.amount) - num(this.state.household), 0);
    }

    money(value) {
        const { symbol, position } = this.state.currency;
        const text = (Math.round(value * 100) / 100).toFixed(2);
        return position === "before" ? `${symbol}${text}` : `${text} ${symbol}`;
    }

    moneyBase(value) {
        const { symbol, position } = this.state.base;
        const text = (Math.round(value * 100) / 100).toFixed(2);
        return position === "before" ? `${symbol}${text}` : `${text} ${symbol}`;
    }

    // ---- store picker (bill) ----
    get typedStore() {
        return this.state.storeText.trim();
    }

    get selectedStore() {
        const name = this.typedStore.toLowerCase();
        return name ? this.state.stores.find((s) => s.name.toLowerCase() === name) : undefined;
    }

    get isNewStore() {
        return Boolean(this.typedStore) && !this.selectedStore;
    }

    get storeSuggestions() {
        const name = this.typedStore.toLowerCase();
        return this.state.stores.filter((s) => !name || s.name.toLowerCase().includes(name)).slice(0, 12);
    }

    // ---- photos ----
    pickPhoto() {
        this.fileRef.el.click();
    }

    async onPhotosChosen(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        for (const file of files) {
            try {
                const url = await shrinkImage(file);
                this.state.photos.push({ thumb: url, full: url, data: url.split(",")[1] });
            } catch (error) {
                this.state.error = _t("That file could not be read as a photo.");
            }
        }
    }

    removePhoto(photo) {
        this.state.photos = this.state.photos.filter((p) => p !== photo);
        if (photo.id) {
            this.state.removedPhotoIds.push(photo.id);
        }
    }

    zoom(photo) {
        this.state.zoom = photo.full;
    }

    // ------------------------------------------------------------------ save / delete

    photoCommands() {
        return [
            ...this.state.photos.filter((p) => p.data).map((p) => [0, 0, { image: p.data }]),
            ...this.state.removedPhotoIds.map((id) => [2, id]),
        ];
    }

    async buildValues() {
        const { state } = this;
        const amount = num(state.amount);
        const notes = state.notes.trim() || false;
        switch (this.kind) {
            case "bill": {
                if (amount <= 0) {
                    throw new Error(_t("Enter the bill total."));
                }
                const household = num(state.household);
                if (household > amount) {
                    throw new Error(_t("The household part can't be more than the bill total."));
                }
                let storeId = this.selectedStore ? this.selectedStore.id : false;
                if (!storeId && this.typedStore) {
                    [storeId] = await this.orm.create("finance.store", [{ name: this.typedStore }]);
                }
                return {
                    total_amount: amount, household_amount: household, store_id: storeId,
                    date: state.date, user_id: state.userId, notes, photo_ids: this.photoCommands(),
                };
            }
            case "housing":
                if (amount <= 0) {
                    throw new Error(_t("Enter the amount."));
                }
                return {
                    kind: state.housingKind, amount, date: state.date, period: `${state.period}-01`,
                    user_id: state.userId, notes, photo_ids: this.photoCommands(),
                };
            case "income":
                this.checkCurrencyInput(amount);
                return {
                    amount, source: state.source, date: state.date, user_id: state.userId, notes,
                    currency_id: state.currencyId, rate: this.isForeign ? num(state.rate) : 1,
                };
            case "saving":
                this.checkCurrencyInput(amount);
                return {
                    amount, kind: state.savingKind, date: state.date, user_id: state.userId,
                    plan_id: state.planId || false, notes,
                    currency_id: state.currencyId, rate: this.isForeign ? num(state.rate) : 1,
                };
            case "plan": {
                if (!state.planName.trim()) {
                    throw new Error(_t("Give the plan a name."));
                }
                const vals = {
                    name: state.planName.trim(), kind: state.planKind, notes,
                    target_date: state.date || false,
                };
                if (amount > 0) {
                    vals.line_ids = [[0, 0, { name: _t("Budget"), amount }]];
                }
                return vals;
            }
        }
    }

    checkCurrencyInput(amount) {
        if (amount <= 0) {
            throw new Error(_t("Enter the amount."));
        }
        if (this.isForeign && num(this.state.rate) <= 0) {
            throw new Error(_t("Enter the exchange rate."));
        }
    }

    async save() {
        this.state.error = "";
        this.state.saving = true;
        try {
            const vals = await this.buildValues();
            if (this.isEdit) {
                await this.orm.write(this.cfg.model, [this.props.resId], vals);
            } else {
                await this.orm.create(this.cfg.model, [vals]);
            }
            if (this.props.onSaved) {
                this.props.onSaved();
            }
            this.props.close();
        } catch (error) {
            // Our own validation messages are plain Errors; server errors carry their own dialog.
            if (error && error.message && !error.data) {
                this.state.error = error.message;
            } else {
                throw error;
            }
        } finally {
            this.state.saving = false;
        }
    }

    askDelete() {
        this.dialogService.add(ConfirmationDialog, {
            title: _t("Delete this entry?"),
            body: _t("It will be removed for good."),
            confirmLabel: _t("Delete"),
            cancelLabel: _t("Keep it"),
            confirm: async () => {
                await this.orm.unlink(this.cfg.model, [this.props.resId]);
                if (this.props.onSaved) {
                    this.props.onSaved();
                }
                this.props.close();
            },
            cancel: () => {},
        });
    }
}

// Spending limits: a small dialog in the same style.
export class FinanceLimitsDialog extends Component {
    static template = "family_finance.LimitsDialog";
    static components = { Dialog };
    static props = { onSaved: { type: Function, optional: true }, close: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            currency: { symbol: "", position: "before" },
            groceries: "",
            housing: "",
            total: "",
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            const [currencies, limits] = await Promise.all([
                loadCurrencies(this.orm),
                this.orm.call("finance.budget", "get_limits", []),
            ]);
            this.state.currency = currencies.base;
            for (const key of ["groceries", "housing", "total"]) {
                this.state[key] = limits[key] ? shown(limits[key]) : "";
            }
        });
    }

    onInput(ev, key) {
        this.state[key] = decimalOnly(ev);
    }

    async save() {
        this.state.saving = true;
        try {
            await this.orm.call("finance.budget", "set_limits", [], {
                groceries: num(this.state.groceries),
                housing: num(this.state.housing),
                total: num(this.state.total),
            });
            if (this.props.onSaved) {
                this.props.onSaved();
            }
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}
