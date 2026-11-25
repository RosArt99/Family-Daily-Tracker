/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MODEL = "finance.crypto.lot";
const CHART_W = 340;
const CHART_H = 170;
const PERIODS = [
    { key: "1m", label: "1M", days: 31 },
    { key: "3m", label: "3M", days: 92 },
    { key: "6m", label: "6M", days: 183 },
    { key: "all", label: "All", days: 0 },
];

export function usd(value, decimals = 2) {
    return (value || 0).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Coin amounts: as many decimals as they need (0.01306, 1 282), nothing more.
export function qty(value) {
    return (value || 0).toLocaleString("en-US", { maximumFractionDigits: 8 });
}

// Prices: a dollar or more with cents, below a dollar (XRP) with four decimals.
export function price(value) {
    return usd(value, Math.abs(value) >= 1000 ? 2 : Math.abs(value) >= 1 ? 2 : 4);
}

// Server datetimes are UTC "YYYY-MM-DD HH:MM:SS".
function fromUtc(text) {
    return text ? new Date(text.replace(" ", "T") + "Z") : null;
}

function toUtc(local) {
    return local ? new Date(local).toISOString().replace("T", " ").slice(0, 19) : false;
}

function toLocalInput(date) {
    const d = date || new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ---------------------------------------------------------------------------------------------
// Add / edit a purchase (one order from the exchange).
// ---------------------------------------------------------------------------------------------
export class CryptoLotDialog extends Component {
    static template = "family_finance.CryptoLotDialog";
    static components = { Dialog };
    static props = {
        coins: Array,
        lot: { type: Object, optional: true },
        coinId: { type: Number, optional: true },
        onSaved: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        const lot = this.props.lot;
        this.state = useState({
            assetId: lot ? lot.asset_id : this.props.coinId || this.props.coins[0].id,
            date: toLocalInput(lot ? fromUtc(lot.date) : null),
            quantity: lot ? String(lot.quantity) : "",
            price: lot ? String(lot.price) : "",
            fee: lot && lot.fee ? String(lot.fee) : "",
            feeIn: lot ? lot.fee_in : "coin",
            total: lot && lot.total ? String(lot.total) : "",
            quote: lot ? lot.quote : "USDT",
            orderType: lot ? lot.order_type : "market",
            orderNo: lot ? lot.order_no : "",
            notes: lot ? lot.notes : "",
            error: "",
            busy: false,
        });
    }

    get coin() {
        return this.props.coins.find((c) => c.id === this.state.assetId);
    }

    num(text) {
        const n = parseFloat(String(text || "").replace(/\s/g, "").replace(",", "."));
        return Number.isFinite(n) ? n : 0;
    }

    // What the order cost if "Total" is left empty.
    get estimatedTotal() {
        const base = this.num(this.state.quantity) * this.num(this.state.price);
        return base + (this.state.feeIn === "usd" ? this.num(this.state.fee) : 0);
    }

    onNumber(ev, field) {
        const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
        ev.target.value = cleaned;
        this.state[field] = cleaned;
    }

    async save() {
        const { state } = this;
        if (this.num(state.quantity) <= 0 || this.num(state.price) <= 0) {
            state.error = "Fill in the amount and the price.";
            return;
        }
        state.busy = true;
        try {
            const data = await this.orm.call(MODEL, "save_lot", [{
                id: this.props.lot ? this.props.lot.id : false,
                asset_id: state.assetId,
                date: toUtc(state.date),
                quantity: this.num(state.quantity),
                price: this.num(state.price),
                fee: this.num(state.fee),
                fee_in: state.feeIn,
                total: this.num(state.total),
                quote: state.quote,
                order_type: state.orderType,
                order_no: state.orderNo,
                notes: state.notes,
            }]);
            this.props.onSaved(data);
            this.props.close();
        } finally {
            state.busy = false;
        }
    }

    usd(v) {
        return usd(v);
    }
}

// ---------------------------------------------------------------------------------------------
// The Crypto screen: total value, a value-over-time chart per coin, and every coin with its lots.
// ---------------------------------------------------------------------------------------------
export class FinanceCrypto extends Component {
    static template = "family_finance.FinanceCrypto";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({ data: null, period: "all", open: {}, loading: false });
        this.periods = PERIODS;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(MODEL, "get_portfolio", []);
        } finally {
            this.state.loading = false;
        }
    }

    // ---- formatting
    usd(v, d) {
        return usd(v, d);
    }
    qty(v) {
        return qty(v);
    }
    price(v) {
        return price(v);
    }
    sign(v) {
        return v < 0 ? "−" : "+";
    }
    pnlClass(v) {
        return v < 0 ? "o_down" : "o_up";
    }
    lotDate(text) {
        const d = fromUtc(text);
        return d ? d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
    }
    get updated() {
        const coin = this.state.data.coins.find((c) => c.price_at);
        const d = coin && fromUtc(coin.price_at);
        return d ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "";
    }

    // ---- chart: one line per coin, value in USD
    setPeriod(key) {
        this.state.period = key;
    }

    get chart() {
        const { days, series } = this.state.data.chart;
        if (!days.length) {
            return null;
        }
        const period = PERIODS.find((p) => p.key === this.state.period);
        const from = period.days ? Math.max(0, days.length - period.days) : 0;
        const shown = days.slice(from);
        const lines = series.map((s) => ({ ...s, values: s.values.slice(from) }));
        const max = Math.max(1, ...lines.flatMap((s) => s.values)) * 1.08;
        const n = Math.max(1, shown.length - 1);
        const x = (i) => (i / n) * CHART_W;
        const y = (v) => CHART_H - (v / max) * CHART_H;
        const label = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
        return {
            width: CHART_W,
            height: CHART_H,
            lines: lines.map((s) => ({
                symbol: s.symbol,
                color: s.color,
                last: s.values[s.values.length - 1],
                points: s.values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "),
            })),
            grid: [0.25, 0.5, 0.75].map((f) => ({ y: (CHART_H * f).toFixed(1), label: usd(max * (1 - f), 0) })),
            xLabels: [label(shown[0]), label(shown[Math.floor(shown.length / 2)]), label(shown[shown.length - 1])],
        };
    }

    // ---- coins and lots
    toggle(coin) {
        this.state.open[coin.id] = !this.state.open[coin.id];
    }

    get coinsHeld() {
        return this.state.data.coins.filter((c) => c.lots.length);
    }

    get coinsList() {
        return this.state.data.coins.map(({ id, symbol, name, color }) => ({ id, symbol, name, color }));
    }

    addLot(coinId) {
        this.dialog.add(CryptoLotDialog, {
            coins: this.coinsList,
            coinId,
            onSaved: (data) => (this.state.data = data),
        });
    }

    editLot(coin, lot) {
        this.dialog.add(CryptoLotDialog, {
            coins: this.coinsList,
            lot: { ...lot, asset_id: coin.id },
            onSaved: (data) => (this.state.data = data),
        });
    }

    deleteLot(coin, lot) {
        this.dialog.add(ConfirmationDialog, {
            title: "Delete purchase",
            body: `Delete the ${qty(lot.quantity)} ${coin.symbol} bought on ${this.lotDate(lot.date)}?`,
            confirmLabel: "Delete",
            confirm: async () => {
                this.state.data = await this.orm.call(MODEL, "delete_lot", [lot.id]);
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("family_finance.crypto", FinanceCrypto);
