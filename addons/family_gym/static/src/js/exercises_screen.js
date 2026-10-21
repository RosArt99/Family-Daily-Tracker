/** @odoo-module **/
/* global Chart */

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";

const COLOR_ME = "#d81f4a";
const COLORS_OTHERS = ["#2f7fd6", "#f0a30a", "#8e5bb5"];
const MUSCLE_GROUPS = [
    ["chest", _t("Chest")],
    ["back", _t("Back")],
    ["legs", _t("Legs")],
    ["shoulders", _t("Shoulders")],
    ["arms", _t("Arms")],
    ["core", _t("Core")],
    ["cardio", _t("Cardio")],
    ["other", _t("Other")],
];
// What kind of training the day was (the calendar square says it); several can be chosen.
const DAY_TYPES = [
    ["legs", _t("Legs")],
    ["upper", _t("Upper")],
    ["back", _t("Back")],
    ["cardio", _t("Cardio")],
    ["full_body", _t("Full body")],
];
const WEEKDAYS = [_t("Mon"), _t("Tue"), _t("Wed"), _t("Thu"), _t("Fri"), _t("Sat"), _t("Sun")];

function pad(n) {
    return String(n).padStart(2, "0");
}

function dateStr(d) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parse(str) {
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d);
}

function addDays(str, days) {
    const d = parse(str);
    d.setDate(d.getDate() + days);
    return dateStr(d);
}

function ts(str) {
    return parse(str).getTime();
}

// "12", "12.5" or "12,5" (phone keyboards); anything else counts as 0.
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

// The Exercises screen. Like the Meals diary it works one day at a time (today by default):
// log the exercises right at the top, see what the day holds, pick another day from the
// calendar squares, and follow an exercise's progress in the chart at the bottom.
export class GymExercises extends Component {
    static template = "family_gym.ExercisesScreen";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.formRef = useRef("form");
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.nextKey = 1;
        this.weekdays = WEEKDAYS;
        this.dayTypes = DAY_TYPES;
        this.muscleGroups = MUSCLE_GROUPS;
        this.state = useState({
            data: null,
            day: null,
            // ---- the log form ----
            text: "",
            newMetric: "strength",
            newMuscle: "other",
            sets: [this.makeSet()],
            notes: "",
            editId: 0,
            last: "",
            error: "",
            saving: false,
            // ---- progress chart ----
            chartExercise: 0,
            preset: "90d",
            chartData: null,
            showOthers: false,
        });
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
            await this.loadChart();
        });
        useEffect(
            () => this.renderChart(),
            () => [this.state.chartData, this.state.showOthers]
        );
        onWillUnmount(() => this.chart && this.chart.destroy());
    }

    makeSet(weight = "", reps = "") {
        return { key: this.nextKey++, weight, reps };
    }

    // ------------------------------------------------------------------ day & calendar

    async load(day, year, month) {
        const data = await this.orm.call("gym.strength_log", "get_exercise_screen", [
            day || this.state.day || false,
            year || false,
            month || false,
        ]);
        this.state.day = data.day;
        this.state.data = data;
    }

    async selectDay(day) {
        this.resetForm();
        await this.load(day);
    }

    async shiftDay(delta) {
        await this.selectDay(addDays(this.state.day, delta));
    }

    async shiftMonth(delta) {
        const { year, month } = this.state.data;
        const d = new Date(year, month - 1 + delta, 1);
        // Keep the same day-of-month selected when it exists, else the 1st.
        const target = new Date(d.getFullYear(), d.getMonth(), Math.min(parse(this.state.day).getDate(), 28));
        this.resetForm();
        await this.load(dateStr(target), d.getFullYear(), d.getMonth() + 1);
    }

    get dayLabel() {
        const data = this.state.data;
        if (data.day === data.today) {
            return _t("Today");
        }
        if (data.day === addDays(data.today, -1)) {
            return _t("Yesterday");
        }
        return parse(data.day).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    }

    get monthLabel() {
        const { year, month } = this.state.data;
        return new Date(year, month - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
    }

    // The squares: blanks to line the 1st up under its weekday, then one per day.
    get cells() {
        const data = this.state.data;
        const cells = [];
        for (let i = 0; i < data.first_weekday; i++) {
            cells.push({ key: `b${i}`, blank: true });
        }
        for (let day = 1; day <= data.month_days; day++) {
            const iso = `${data.year}-${pad(data.month)}-${pad(day)}`;
            const info = data.days[iso];
            const tags = info ? info.tags : [];
            cells.push({
                key: iso,
                iso,
                day,
                visit: Boolean(info),
                label: tags.slice(0, 3).join("/"),
                today: iso === data.today,
                selected: iso === data.day,
                future: iso > data.today,
            });
        }
        return cells;
    }

    get isFuture() {
        return this.state.data.day > this.state.data.today;
    }

    // The kinds of training chosen for the selected day (old chest/shoulders/arms workouts count as
    // "Upper"). Several can be on at once: Legs + Cardio.
    get dayTypeKeys() {
        return this.state.data.workout_types;
    }

    isDayType(key) {
        return this.dayTypeKeys.includes(key);
    }

    // Tap a type to add it, tap it again to take it off (the visit itself stays).
    async toggleDayType(key) {
        await this.orm.call("gym.workout", "toggle_type", [this.state.data.day, key]);
        await this.load();
    }

    async toggleVisit() {
        await this.orm.call("gym.workout", "toggle_visit", [this.state.data.day]);
        await this.load();
    }

    // ------------------------------------------------------------------ log form: exercise

    get typed() {
        return this.state.text.trim();
    }

    get exercises() {
        return this.state.data.exercises;
    }

    get selected() {
        const name = this.typed.toLowerCase();
        return name ? this.exercises.find((ex) => ex.name.toLowerCase() === name) : undefined;
    }

    get isNew() {
        return Boolean(this.typed) && !this.selected;
    }

    // Your recent exercises first, then the rest; narrowed as you type.
    get suggestions() {
        const name = this.typed.toLowerCase();
        const recent = this.state.data.recent_ids;
        const rank = (ex) => (recent.includes(ex.id) ? recent.indexOf(ex.id) : 1e6);
        return this.exercises
            .filter((ex) => !name || ex.name.toLowerCase().includes(name))
            .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
            .slice(0, 12);
    }

    // Reps-only exercises (pull-ups) have no weight column.
    get repsOnly() {
        return this.selected ? this.selected.metric === "reps" : this.state.newMetric === "reps";
    }

    async onTextInput(ev) {
        this.state.text = ev.target.value;
        this.state.last = "";
        if (this.selected) {
            await this.loadLast();
        }
    }

    async pick(exercise) {
        this.state.text = exercise.name;
        await this.loadLast();
        this.state.chartExercise = exercise.id;
        await this.loadChart();
    }

    async loadLast() {
        const exercise = this.selected;
        if (!exercise) {
            return;
        }
        const last = await this.orm.call("gym.strength_log", "get_last_session", [exercise.id]);
        this.state.last = last ? `${last.date}:  ${last.summary}` : "";
    }

    // ------------------------------------------------------------------ log form: sets

    addSet() {
        const previous = this.state.sets[this.state.sets.length - 1];
        this.state.sets.push(this.makeSet(previous ? previous.weight : "", previous ? previous.reps : ""));
    }

    removeSet(set) {
        this.state.sets = this.state.sets.filter((other) => other !== set);
        if (!this.state.sets.length) {
            this.state.sets.push(this.makeSet());
        }
    }

    onSetInput(ev, set, field) {
        set[field] = decimalOnly(ev);
    }

    get filledSets() {
        return this.state.sets.filter((set) => num(set.reps) > 0 || (!this.repsOnly && num(set.weight) > 0));
    }

    get best() {
        const values = this.filledSets.map((set) => (this.repsOnly ? num(set.reps) : num(set.weight)));
        return values.length ? Math.max(...values) : 0;
    }

    get volume() {
        return this.filledSets.reduce((sum, set) => sum + num(set.weight) * num(set.reps), 0);
    }

    fmt(value) {
        return shown(value);
    }

    resetForm() {
        const s = this.state;
        s.text = "";
        s.newMetric = "strength";
        s.newMuscle = "other";
        s.sets = [this.makeSet()];
        s.notes = "";
        s.editId = 0;
        s.last = "";
        s.error = "";
    }

    // ------------------------------------------------------------------ log form: save / edit / delete

    async save() {
        const { state } = this;
        state.error = "";
        if (!this.typed) {
            state.error = _t("Choose or type an exercise.");
            return;
        }
        if (!this.filledSets.length) {
            state.error = _t("Add at least one set.");
            return;
        }
        state.saving = true;
        try {
            const exercise = this.selected;
            const exerciseId = await this.orm.call("gym.strength_log", "save_exercise", [
                {
                    id: state.editId || false,
                    date: state.day,
                    exercise_id: exercise ? exercise.id : false,
                    new_name: exercise ? false : this.typed,
                    metric: state.newMetric,
                    muscle_group: state.newMuscle,
                    notes: state.notes,
                    sets: this.filledSets.map((set) => ({ weight: num(set.weight), reps: Math.round(num(set.reps)) })),
                },
            ]);
            this.resetForm();
            await this.load();
            // Follow what was just logged in the chart.
            const saved = this.state.data.entries.find((entry) => entry.id === exerciseId);
            if (saved) {
                this.state.chartExercise = saved.exercise_id;
                await this.loadChart();
            }
        } finally {
            state.saving = false;
        }
    }

    editEntry(entry) {
        const s = this.state;
        s.editId = entry.id;
        s.text = entry.name;
        s.sets = entry.sets.map((item) => this.makeSet(item.weight ? shown(item.weight) : "", String(item.reps)));
        if (!s.sets.length) {
            s.sets = [this.makeSet()];
        }
        s.notes = entry.notes;
        s.error = "";
        s.last = "";
        if (this.formRef.el) {
            this.formRef.el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    cancelEdit() {
        this.resetForm();
    }

    deleteEntry(entry) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete entry"),
            body: _t("Remove %s from this day?", entry.name),
            confirmLabel: _t("Delete"),
            confirm: async () => {
                await this.orm.call("gym.strength_log", "delete_exercise", [entry.id]);
                if (this.state.editId === entry.id) {
                    this.resetForm();
                }
                await this.load();
                await this.loadChart();
            },
            cancel: () => {},
        });
    }

    // ------------------------------------------------------------------ progress chart

    get chartExercises() {
        const recent = this.state.data.recent_ids;
        return recent
            .map((id) => this.exercises.find((ex) => ex.id === id))
            .filter(Boolean)
            .slice(0, 12);
    }

    get presets() {
        return [
            { key: "30d", label: "30D" },
            { key: "90d", label: "90D" },
            { key: "1y", label: "1Y" },
            { key: "all", label: _t("All") },
        ];
    }

    async loadChart() {
        const { state } = this;
        if (!state.chartExercise) {
            state.chartExercise = this.state.data.recent_ids[0] || 0;
        }
        if (!state.chartExercise) {
            state.chartData = null;
            return;
        }
        const today = this.state.data.today;
        let from;
        if (state.preset === "30d") {
            from = addDays(today, -29);
        } else if (state.preset === "90d") {
            from = addDays(today, -89);
        } else if (state.preset === "1y") {
            from = addDays(today, -364);
        } else {
            from = false;
        }
        const data = await this.orm.call("gym.strength_log", "get_exercise_progress", [
            state.chartExercise,
            from,
            today,
        ]);
        if (!from) {
            data.date_from = data.first_date;
        }
        state.chartData = data;
    }

    async setPreset(key) {
        this.state.preset = key;
        await this.loadChart();
    }

    async chooseChartExercise(id) {
        this.state.chartExercise = id;
        await this.loadChart();
    }

    toggleOthers() {
        this.state.showOthers = !this.state.showOthers;
    }

    get othersWithPoints() {
        return this.state.chartData ? this.state.chartData.others.filter((o) => o.points.length) : [];
    }

    get othersLabel() {
        return this.othersWithPoints.map((o) => o.name.split(" ")[0]).join(", ");
    }

    get unit() {
        return this.state.chartData && this.state.chartData.exercise.metric === "reps" ? _t("reps") : "kg";
    }

    renderChart() {
        const canvas = this.canvasRef.el;
        const data = this.state.chartData;
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        if (!canvas || !data) {
            return;
        }
        const from = ts(data.date_from);
        const to = ts(data.date_to);
        const ctx = canvas.getContext("2d");
        const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 240);
        gradient.addColorStop(0, "rgba(216, 31, 74, 0.28)");
        gradient.addColorStop(1, "rgba(216, 31, 74, 0)");
        const toXY = (points) => points.map(([day, value]) => ({ x: ts(day), y: value }));
        const datasets = [
            {
                label: _t("Me"),
                data: toXY(data.mine),
                borderColor: COLOR_ME,
                backgroundColor: gradient,
                fill: true,
                tension: 0.25,
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
        if (this.state.showOthers) {
            this.othersWithPoints.forEach((other, index) => {
                const color = COLORS_OTHERS[index % COLORS_OTHERS.length];
                datasets.push({
                    label: other.name,
                    data: toXY(other.points),
                    borderColor: color,
                    backgroundColor: color,
                    borderWidth: 3,
                    tension: 0.25,
                    pointRadius: 4,
                    pointBackgroundColor: "#fff",
                    pointBorderColor: color,
                    pointBorderWidth: 3,
                    spanGaps: true,
                    fill: false,
                });
            });
        }
        const unit = this.unit;
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
                        callbacks: { label: (item) => ` ${item.dataset.label}: ${item.parsed.y} ${unit}` },
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
                        grace: "10%",
                        grid: { color: "rgba(196, 30, 63, 0.08)" },
                        ticks: { color: "#8a6f76" },
                        title: { display: true, text: unit, color: "#8a6f76" },
                    },
                },
            },
        });
    }
}

registry.category("actions").add("family_gym.exercises", GymExercises);
