/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

const ICON_DIR = "/family_gym/static/src/img/icons";
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
    // 100 -> "100", 102.5 -> "102.5"
    return String(Math.round(value * 100) / 100);
}

function todayString() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// "Add" on the Weight graph: a big weight in the header, pre-filled with your last weigh-in so
// a small change is one or two taps.
export class WeightEntryDialog extends Component {
    static template = "family_gym.WeightEntryDialog";
    static components = { Dialog };
    static props = { onSaved: { type: Function, optional: true }, close: Function };

    setup() {
        this.orm = useService("orm");
        this.iconStyle = `--gym-icon: url('${ICON_DIR}/scale.svg')`;
        this.state = useState({
            weight: "",
            date: todayString(),
            notes: "",
            last: null,
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            const [last] = await this.orm.searchRead(
                "gym.weight_log",
                [["user_id", "=", session.uid || session.user_id]],
                ["weight", "date"],
                { limit: 1, order: "date desc, id desc" }
            );
            if (last) {
                this.state.last = last;
                this.state.weight = shown(last.weight);
            }
        });
    }

    fmt(value) {
        return shown(value);
    }

    onWeightInput(ev) {
        this.state.weight = decimalOnly(ev);
    }

    nudge(delta) {
        this.state.weight = shown(Math.max(0, num(this.state.weight) + delta));
    }

    async save() {
        const weight = num(this.state.weight);
        this.state.error = "";
        if (weight <= 0) {
            this.state.error = _t("Enter your weight.");
            return;
        }
        this.state.saving = true;
        try {
            await this.orm.create("gym.weight_log", [
                { weight, date: this.state.date, notes: this.state.notes.trim() || false },
            ]);
            if (this.props.onSaved) {
                this.props.onSaved();
            }
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }
}

// "Add" on the Exercises graph: pick (or type a new) exercise, then one row per set. The graph
// shows the heaviest set of the day.
export class ExerciseEntryDialog extends Component {
    static template = "family_gym.ExerciseEntryDialog";
    static components = { Dialog };
    static props = {
        exerciseId: { type: Number, optional: true },
        onSaved: { type: Function, optional: true },
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.muscleGroups = MUSCLE_GROUPS;
        this.iconStyle = `--gym-icon: url('${ICON_DIR}/dumbbell.svg')`;
        this.nextKey = 1;
        this.state = useState({
            text: "",
            exercises: [],
            newMetric: "strength",
            newMuscle: "other",
            sets: [this.makeSet()],
            notes: "",
            last: "",
            error: "",
            saving: false,
        });
        onWillStart(async () => {
            this.state.exercises = await this.orm.searchRead("gym.exercise", [], ["name", "metric"], {
                order: "name",
            });
            const preset = this.state.exercises.find((ex) => ex.id === this.props.exerciseId);
            if (preset) {
                this.state.text = preset.name;
                await this.loadLast();
            }
        });
    }

    makeSet(weight = "", reps = "") {
        return { key: this.nextKey++, weight, reps };
    }

    // ---- exercise picker ----
    get typed() {
        return this.state.text.trim();
    }

    get selected() {
        const name = this.typed.toLowerCase();
        return name ? this.state.exercises.find((ex) => ex.name.toLowerCase() === name) : undefined;
    }

    get isNew() {
        return Boolean(this.typed) && !this.selected;
    }

    get suggestions() {
        const name = this.typed.toLowerCase();
        return this.state.exercises.filter((ex) => !name || ex.name.toLowerCase().includes(name));
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
    }

    // "Last time: 100×12 · 120×8" as a nudge for what to lift today.
    async loadLast() {
        const exercise = this.selected;
        if (!exercise) {
            return;
        }
        const [last] = await this.orm.searchRead(
            "gym.strength_log",
            [["exercise_id", "=", exercise.id], ["user_id", "=", session.uid || session.user_id]],
            ["summary", "date"],
            { limit: 1, order: "date desc, id desc" }
        );
        this.state.last = last ? `${last.date}:  ${last.summary}` : "";
    }

    // ---- sets ----
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

    // ---- save ----
    async save() {
        const { state } = this;
        state.error = "";
        if (!this.typed) {
            state.error = _t("Choose or type an exercise.");
            return;
        }
        const sets = this.filledSets;
        if (!sets.length) {
            state.error = _t("Add at least one set.");
            return;
        }
        state.saving = true;
        try {
            let exerciseId = this.selected && this.selected.id;
            if (!exerciseId) {
                [exerciseId] = await this.orm.create("gym.exercise", [
                    { name: this.typed, metric: state.newMetric, muscle_group: state.newMuscle },
                ]);
            }
            await this.orm.create("gym.strength_log", [
                {
                    exercise_id: exerciseId,
                    notes: state.notes.trim() || false,
                    set_ids: sets.map((set, index) => [
                        0,
                        0,
                        {
                            sequence: 10 * (index + 1),
                            weight: this.repsOnly ? 0 : num(set.weight),
                            reps: Math.round(num(set.reps)),
                        },
                    ]),
                },
            ]);
            if (this.props.onSaved) {
                this.props.onSaved({ exerciseId });
            }
            this.props.close();
        } finally {
            state.saving = false;
        }
    }
}
