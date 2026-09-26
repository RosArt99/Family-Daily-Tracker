/** @odoo-module **/

import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { useService } from "@web/core/utils/hooks";
import { getGroupBy } from "@web/search/utils/group_by";
import { graphView } from "@web/views/graph/graph_view";
import { GraphRenderer } from "@web/views/graph/graph_renderer";
import { onMounted, onWillStart } from "@odoo/owl";
import { ExerciseEntryDialog, WeightEntryDialog } from "./gym_entry_dialogs";

// The stock graph view is built for reports (measures, bar/pie, stacking, sorting). The Weight
// and Exercises graphs are "one line per person over time", so this variant drops all of that
// and offers what you actually use in the gym: Day/Week/Month, a From/To period, an exercise
// picker (Exercises only) and a button to add an entry without leaving the graph.
export class GymGraphRenderer extends GraphRenderer {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        this.exercises = [];
        onWillStart(() => this.loadExercises());
        onMounted(() => this.pickDefaultExercise());
    }

    // ------------------------------------------------------------------ view flavour

    get isExerciseGraph() {
        return this.props.model.metaData.resModel === "gym.strength_log";
    }

    // ------------------------------------------------------------------ interval

    get intervals() {
        return [
            { value: "day", label: "Day" },
            { value: "week", label: "Week" },
            { value: "month", label: "Month" },
        ];
    }

    get currentInterval() {
        const dateGroup = this.props.model.metaData.groupBy.find((gb) => gb.fieldName === "date");
        return dateGroup && dateGroup.interval;
    }

    async onIntervalSelected(interval) {
        const model = this.props.model;
        const { fields } = model.metaData;
        // `initialGroupBy` is what the model falls back to when the search has no group-by, so
        // setting it also keeps the chosen interval when the filters change.
        model.initialGroupBy = [
            getGroupBy(`date:${interval}`, fields),
            getGroupBy("user_id", fields),
        ];
        await this.reload();
    }

    async reload() {
        const model = this.props.model;
        await model.load(model.searchParams);
        model.notify();
    }

    // ------------------------------------------------------------------ own search filters
    // From/To and the exercise picker are ordinary search filters (they show up as facets with
    // an x), so they survive interval changes and are cleared by removing the facet.

    findFilter(key) {
        const { query, searchItems } = this.env.searchModel;
        for (const { searchItemId } of query) {
            if (searchItems[searchItemId].gymKey === key) {
                return searchItems[searchItemId];
            }
        }
        return null;
    }

    setFilter(key, filter) {
        const searchModel = this.env.searchModel;
        // One notification for the whole swap, otherwise the graph would load twice.
        searchModel.blockNotification = true;
        const current = this.findFilter(key);
        if (current) {
            searchModel.deactivateGroup(current.groupId);
        }
        if (filter) {
            searchModel.createNewFilters([
                {
                    description: filter.description,
                    domain: JSON.stringify(filter.domain),
                    invisible: "True",
                    gymKey: key,
                    gymData: filter.data,
                },
            ]);
        }
        searchModel.blockNotification = false;
        searchModel._notify();
    }

    get dateFrom() {
        const item = this.findFilter("range");
        return item ? item.gymData.from : "";
    }

    get dateTo() {
        const item = this.findFilter("range");
        return item ? item.gymData.to : "";
    }

    onFromChange(ev) {
        this.applyRange(ev.target.value, this.dateTo);
    }

    onToChange(ev) {
        this.applyRange(this.dateFrom, ev.target.value);
    }

    applyRange(from, to) {
        if (from && to && from > to) {
            [from, to] = [to, from];
        }
        if (!from && !to) {
            return this.setFilter("range", null);
        }
        const domain = [];
        if (from) {
            domain.push(["date", ">=", from]);
        }
        if (to) {
            domain.push(["date", "<=", to]);
        }
        const description = from && to ? `${from} → ${to}` : from ? `From ${from}` : `Until ${to}`;
        this.setFilter("range", { description, domain, data: { from, to } });
    }

    // ------------------------------------------------------------------ exercises

    async loadExercises() {
        if (this.isExerciseGraph) {
            this.exercises = await this.orm.searchRead("gym.exercise", [], ["name"], { order: "name" });
        }
    }

    get selectedExerciseId() {
        const item = this.findFilter("exercise");
        return item ? item.gymData.id : 0;
    }

    onExerciseChange(ev) {
        this.applyExercise(parseInt(ev.target.value, 10));
    }

    applyExercise(id) {
        const exercise = this.exercises.find((ex) => ex.id === id);
        if (!exercise) {
            return this.setFilter("exercise", null);
        }
        this.setFilter("exercise", {
            description: exercise.name,
            domain: [["exercise_id", "=", id]],
            data: { id, name: exercise.name },
        });
    }

    // A graph of every exercise mixed together means nothing, so start on the exercise you
    // logged last (yours first, else anyone's, else the first one in the list).
    async pickDefaultExercise() {
        if (!this.isExerciseGraph || this.selectedExerciseId || !this.exercises.length) {
            return;
        }
        let [last] = await this.orm.searchRead(
            "gym.strength_log", [["user_id", "=", session.uid || session.user_id]], ["exercise_id"],
            { limit: 1, order: "date desc, id desc" }
        );
        if (!last) {
            [last] = await this.orm.searchRead(
                "gym.strength_log", [], ["exercise_id"], { limit: 1, order: "date desc, id desc" }
            );
        }
        this.applyExercise(last ? last.exercise_id[0] : this.exercises[0].id);
    }

    // ------------------------------------------------------------------ add an entry

    onAddClicked() {
        if (this.isExerciseGraph) {
            this.dialogService.add(ExerciseEntryDialog, {
                exerciseId: this.selectedExerciseId || undefined,
                onSaved: async ({ exerciseId }) => {
                    await this.loadExercises();
                    // Jump to what was just logged so the new point is on screen.
                    this.applyExercise(exerciseId);
                },
            });
        } else {
            this.dialogService.add(WeightEntryDialog, { onSaved: () => this.reload() });
        }
    }

    // ------------------------------------------------------------------ chart tweaks

    // Odoo forces every graph's value axis to include 0. For body weight or a barbell lift
    // that flattens a few kilos of progress into a straight line, so let the axis zoom in.
    getScaleOptions() {
        const scales = super.getScaleOptions(...arguments);
        if (scales.y) {
            delete scales.y.suggestedMin;
            delete scales.y.suggestedMax;
        }
        return scales;
    }

    getLineChartData() {
        const data = super.getLineChartData(...arguments);
        // Odoo fills periods without data with 0 (or `false`, which is what the server returns
        // for an empty sum), which drags a line to the floor whenever someone skipped a period.
        // A real weight or lift is never 0, so treat anything that is not a positive number as
        // "nothing logged" and let the line bridge the gap. Odoo also invents an empty "None"
        // series for those filler periods: drop series that have no entry at all.
        for (const dataset of data.datasets) {
            dataset.data = dataset.data.map((value) =>
                typeof value === "number" && value > 0 ? value : null
            );
            dataset.spanGaps = true;
        }
        data.datasets = data.datasets.filter((dataset) =>
            dataset.data.some((value) => value !== null)
        );
        return data;
    }
}

const gymGraphView = {
    ...graphView,
    Renderer: GymGraphRenderer,
    buttonTemplate: "family_gym.GymGraph.Buttons",
    searchMenuTypes: ["filter", "favorite"],
};
registry.category("views").add("gym_weight_graph", gymGraphView);
registry.category("views").add("gym_exercise_graph", gymGraphView);
