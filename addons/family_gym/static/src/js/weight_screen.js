/** @odoo-module **/
/* global Chart */

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { WeightEntryDialog } from "./gym_entry_dialogs";

// Colours: bright on purpose (the stock Odoo graph was grey and gloomy). Me = the app's crimson,
// the plan = green, the others take turns on the rest.
const COLOR_ME = "#d81f4a";
const COLOR_PLAN = "#1fa56a";
const COLORS_OTHERS = ["#2f7fd6", "#f0a30a", "#8e5bb5"];

// BMI bands as on a phone scale app: [upper bound, colour, label].
const BMI_BANDS = [
    [18.5, "#5bb9ea", _t("Underweight")],
    [25, "#5fd08a", _t("Normal weight")],
    [30, "#ffd54a", _t("Overweight")],
    [35, "#ffa94d", _t("Obese I")],
    [40, "#ff7a7a", _t("Obese II")],
    [Infinity, "#ff6fa5", _t("Obese III")],
];
const BMI_MIN = 15;
const BMI_MAX = 45;

function num(value) {
    const n = parseFloat(String(value).replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}

function decimalOnly(ev) {
    const cleaned = ev.target.value.replace(/[^\d.,]/g, "");
    ev.target.value = cleaned;
    return cleaned;
}

function pad(n) {
    return String(n).padStart(2, "0");
}

function dateStr(d) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// "2026-10-20" -> local midnight in ms (no time zone surprises)
function ts(str) {
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d).getTime();
}

function addDays(str, days) {
    const [y, m, d] = str.split("-").map(Number);
    return dateStr(new Date(y, m - 1, d + days));
}

function prettyDate(str) {
    if (!str) {
        return "";
    }
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

// ---------------------------------------------------------------------------------------------
// The Weight screen
// ---------------------------------------------------------------------------------------------
export class GymWeight extends Component {
    static template = "family_gym.WeightScreen";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.state = useState({
            data: null,
            preset: "30d",
            from: "",
            to: "",
            showPlan: true,
            showOthers: false,
        });
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
            // With a plan, open on the plan's own period: that is the picture you came for.
            if (this.plan) {
                await this.setPreset("plan");
            }
        });
        useEffect(
            () => this.renderChart(),
            () => [this.state.data, this.state.showPlan, this.state.showOthers]
        );
        onWillUnmount(() => this.chart && this.chart.destroy());
    }

    async load(from, to) {
        const data = await this.orm.call("gym.weight_log", "get_weight_screen", [from || false, to || false]);
        this.state.from = data.date_from;
        this.state.to = data.date_to;
        this.state.data = data;
    }

    // ---- period ----
    get presets() {
        const presets = [
            { key: "7d", label: "7D" },
            { key: "30d", label: "30D" },
            { key: "90d", label: "90D" },
            { key: "all", label: _t("All") },
        ];
        if (this.plan) {
            presets.push({ key: "plan", label: _t("Plan") });
        }
        return presets;
    }

    async setPreset(key) {
        const data = this.state.data;
        const today = data.today;
        let from;
        let to = today;
        if (key === "7d") {
            from = addDays(today, -6);
        } else if (key === "30d") {
            from = addDays(today, -29);
        } else if (key === "90d") {
            from = addDays(today, -89);
        } else if (key === "all") {
            from = data.first_date;
        } else {
            from = this.plan.start_date;
            to = this.plan.target_date;
        }
        this.state.preset = key;
        await this.load(from, to);
    }

    async onRangeChange() {
        const from = this.state.from;
        const to = this.state.to;
        if (!from || !to) {
            return;
        }
        this.state.preset = "custom";
        await this.load(from, to);
    }

    onFromInput(ev) {
        this.state.from = ev.target.value;
        this.onRangeChange();
    }

    onToInput(ev) {
        this.state.to = ev.target.value;
        this.onRangeChange();
    }

    // ---- derived values ----
    get plan() {
        const plan = this.state.data && this.state.data.plan;
        return plan && plan.ready ? plan : null;
    }

    get others() {
        return this.state.data.others.filter((o) => o.points.length);
    }

    get othersLabel() {
        const names = this.others.map((o) => o.name.split(" ")[0]);
        return names.length ? names.join(", ") : "";
    }

    toggleOthers() {
        this.state.showOthers = !this.state.showOthers;
    }

    togglePlan() {
        this.state.showPlan = !this.state.showPlan;
    }

    fmt(value) {
        return value === null || value === undefined ? "–" : (Math.round(value * 10) / 10).toFixed(1);
    }

    prettyDate(str) {
        return prettyDate(str);
    }

    get last() {
        return this.state.data.last;
    }

    get deltaClass() {
        const delta = this.last && this.last.delta;
        if (!delta) {
            return "";
        }
        // Down is good when losing (or no plan), up is good when gaining.
        const goodDown = !this.plan || this.plan.goal === "loss";
        return (delta < 0) === goodDown ? "o_good" : "o_bad";
    }

    get bmi() {
        const bmi = this.state.data.bmi;
        if (!bmi) {
            return null;
        }
        const band = BMI_BANDS.find(([limit]) => bmi < limit);
        const position = Math.min(100, Math.max(0, ((bmi - BMI_MIN) / (BMI_MAX - BMI_MIN)) * 100));
        return { value: bmi, label: band[2], position };
    }

    get bmiBands() {
        let previous = BMI_MIN;
        return BMI_BANDS.map(([limit, color]) => {
            const upper = Math.min(limit, BMI_MAX);
            const width = ((upper - previous) / (BMI_MAX - BMI_MIN)) * 100;
            previous = upper;
            return { color, width };
        });
    }

    get bmiTicks() {
        return [18.5, 25, 30, 35, 40].map((value) => ({
            value,
            position: ((value - BMI_MIN) / (BMI_MAX - BMI_MIN)) * 100,
        }));
    }

    // What the plan says you should weigh today, to compare with the scale.
    get planToday() {
        const plan = this.plan;
        if (!plan) {
            return null;
        }
        const today = ts(this.state.data.today);
        const points = plan.points.map(([day, weight]) => [ts(day), weight]);
        if (today < points[0][0] || today > points[points.length - 1][0]) {
            return null;
        }
        for (let i = 1; i < points.length; i++) {
            if (today <= points[i][0]) {
                const [t0, w0] = points[i - 1];
                const [t1, w1] = points[i];
                return t1 === t0 ? w1 : w0 + ((w1 - w0) * (today - t0)) / (t1 - t0);
            }
        }
        return null;
    }

    get planStatus() {
        const planned = this.planToday;
        const last = this.last;
        if (planned === null || !last) {
            return null;
        }
        const diff = last.weight - planned;
        const ahead = this.plan.goal === "loss" ? diff < 0 : diff > 0;
        if (Math.abs(diff) < 0.1) {
            return { text: _t("Right on plan"), cls: "o_good" };
        }
        const kg = Math.abs(diff).toFixed(1);
        return ahead
            ? { text: _t("%s kg ahead of plan", kg), cls: "o_good" }
            : { text: _t("%s kg behind plan", kg), cls: "o_bad" };
    }

    // ---- actions ----
    addWeight() {
        this.dialogService.add(WeightEntryDialog, { onSaved: () => this.load(this.state.from, this.state.to) });
    }

    openPlan() {
        this.dialogService.add(WeightPlanDialog, { onSaved: () => this.load(this.state.from, this.state.to) });
    }

    openAll() {
        this.actionService.doAction("family_gym.action_gym_weight_log");
    }

    // ---- chart ----
    renderChart() {
        const canvas = this.canvasRef.el;
        const data = this.state.data;
        if (!canvas || !data) {
            return;
        }
        if (this.chart) {
            this.chart.destroy();
        }
        const from = ts(data.date_from);
        const to = ts(data.date_to);
        const ctx = canvas.getContext("2d");
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 260);
        gradient.addColorStop(0, "rgba(216, 31, 74, 0.28)");
        gradient.addColorStop(1, "rgba(216, 31, 74, 0)");

        const toXY = (points) => points.map(([day, weight]) => ({ x: ts(day), y: weight }));
        const datasets = [
            {
                label: data.me.name,
                data: toXY(data.mine),
                borderColor: COLOR_ME,
                backgroundColor: gradient,
                fill: true,
                tension: 0.3,
                borderWidth: 3,
                pointRadius: 5,
                pointHoverRadius: 7,
                pointBackgroundColor: "#fff",
                pointBorderColor: COLOR_ME,
                pointBorderWidth: 3,
                spanGaps: true,
                clip: false,
            },
        ];
        if (this.state.showPlan && this.plan) {
            const inRange = this.plan.points.filter(([day]) => ts(day) >= from && ts(day) <= to);
            datasets.push({
                label: _t("Plan"),
                data: toXY(inRange),
                borderColor: COLOR_PLAN,
                borderDash: [9, 6],
                borderWidth: 3,
                pointRadius: 0,
                pointHoverRadius: 4,
                fill: false,
                tension: 0.2,
            });
        }
        if (this.state.showOthers) {
            this.others.forEach((other, index) => {
                const color = COLORS_OTHERS[index % COLORS_OTHERS.length];
                datasets.push({
                    label: other.name,
                    data: toXY(other.points),
                    borderColor: color,
                    backgroundColor: color,
                    borderWidth: 3,
                    tension: 0.3,
                    pointRadius: 4,
                    pointBackgroundColor: "#fff",
                    pointBorderColor: color,
                    pointBorderWidth: 3,
                    spanGaps: true,
                    fill: false,
                });
            });
        }
        this.chart = new Chart(canvas, {
            type: "line",
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "nearest", intersect: false, axis: "x" },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#3d1f27",
                        titleColor: "#fff",
                        bodyColor: "#fff",
                        padding: 10,
                        cornerRadius: 10,
                        callbacks: { label: (item) => ` ${item.dataset.label}: ${item.parsed.y.toFixed(1)} kg` },
                    },
                },
                scales: {
                    x: {
                        type: "time",
                        min: from,
                        max: to,
                        time: {
                            tooltipFormat: "d MMM yyyy",
                            displayFormats: { day: "d MMM", week: "d MMM", month: "MMM yyyy", year: "yyyy" },
                        },
                        grid: { color: "rgba(196, 30, 63, 0.08)" },
                        ticks: { color: "#8a6f76", maxRotation: 0, autoSkipPadding: 14 },
                    },
                    y: {
                        grace: "8%",
                        grid: { color: "rgba(196, 30, 63, 0.08)" },
                        ticks: { color: "#8a6f76", callback: (value) => `${value}` },
                        title: { display: true, text: "kg", color: "#8a6f76" },
                    },
                },
            },
        });
    }
}

registry.category("actions").add("family_gym.weight", GymWeight);

// ---------------------------------------------------------------------------------------------
// The weight plan: who you are, where you start, where you want to be and when
// ---------------------------------------------------------------------------------------------
export class WeightPlanDialog extends Component {
    static template = "family_gym.WeightPlanDialog";
    static components = { Dialog };
    static props = { onSaved: { type: Function, optional: true }, close: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            sex: false,
            age: "",
            height: "",
            startWeight: "",
            startDate: "",
            targetWeight: "",
            targetDate: "",
            days: 3,
            setCalories: true,
            plan: null,
            hadPlan: false,
            error: "",
            saving: false,
        });
        this.previewDebounced = useDebounced(() => this.preview(), 300);
        onWillStart(async () => {
            const { values, plan } = await this.orm.call("gym.profile", "get_plan_form", []);
            const s = this.state;
            s.sex = values.sex;
            s.age = values.age ? String(values.age) : "";
            s.height = values.height_cm ? String(values.height_cm) : "";
            s.startWeight = values.start_weight ? String(values.start_weight) : "";
            s.startDate = values.start_date;
            s.targetWeight = values.target_weight ? String(values.target_weight) : "";
            s.targetDate = values.target_date || "";
            s.days = values.days_per_week;
            s.plan = plan;
            s.hadPlan = Boolean(values.target_weight);
        });
    }

    get values() {
        const s = this.state;
        return {
            sex: s.sex,
            age: num(s.age),
            height_cm: num(s.height),
            start_weight: num(s.startWeight),
            start_date: s.startDate || false,
            target_weight: num(s.targetWeight),
            target_date: s.targetDate || false,
            days_per_week: s.days,
        };
    }

    async preview() {
        this.state.error = "";
        this.state.plan = await this.orm.call("gym.profile", "preview_plan", [this.values]);
    }

    changed() {
        this.previewDebounced();
    }

    setSex(sex) {
        this.state.sex = sex;
        this.changed();
    }

    onNumber(ev, key) {
        this.state[key] = decimalOnly(ev);
        this.changed();
    }

    onDate(key) {
        this.changed();
    }

    stepDays(delta) {
        this.state.days = Math.max(0, Math.min(7, this.state.days + delta));
        this.changed();
    }

    nudge(key, delta) {
        this.state[key] = String(Math.max(0, Math.round((num(this.state[key]) + delta) * 10) / 10));
        this.changed();
    }

    get plan() {
        return this.state.plan;
    }

    get ready() {
        return Boolean(this.plan && this.plan.ready);
    }

    get headline() {
        const plan = this.plan;
        if (!this.ready) {
            return plan && plan.message ? plan.message : _t("Fill in the details below");
        }
        const kg = Math.abs(plan.target_weight - plan.start_weight).toFixed(1);
        return `${plan.goal === "loss" ? _t("Lose") : _t("Gain")} ${kg} kg`;
    }

    get missingText() {
        const plan = this.plan;
        return plan && !plan.ready && plan.missing && plan.missing.length ? _t("Still needed: ") + plan.missing.join(", ") : "";
    }

    prettyDate(str) {
        return prettyDate(str);
    }

    async save() {
        this.state.error = "";
        this.state.saving = true;
        try {
            await this.orm.call("gym.profile", "save_plan", [this.values, this.state.setCalories]);
            if (this.props.onSaved) {
                this.props.onSaved();
            }
            this.props.close();
        } catch (error) {
            if (error && error.data && error.data.message) {
                this.state.error = error.data.message;
            } else {
                throw error;
            }
        } finally {
            this.state.saving = false;
        }
    }

    async clear() {
        await this.orm.call("gym.profile", "clear_plan", []);
        if (this.props.onSaved) {
            this.props.onSaved();
        }
        this.props.close();
    }
}
